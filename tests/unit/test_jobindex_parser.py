from __future__ import annotations

import json
import unittest

from jobindex_scraper.models import CategoryRecord
from jobindex_scraper.listing.jobindex_parser import ListingParseError, parse_jobindex_listing_page


class JobindexParserTests(unittest.TestCase):
    def test_parse_jobindex_listing_page_extracts_listing_observation(self) -> None:
        fragment_html = """
        <div id="jobad-wrapper-h123" data-jobsearch_position='1'>
            <div class="jix-toolbar-top__company">
                <a href="https://example.com/careers">Example Company</a>
            </div>
            <h4><a href="/jobannonce/example-job">Senior Developer</a></h4>
            <div class="jobad-element-area"><span>Odense</span></div>
            <div class="jix-toolbar__pubdate"><time datetime="2026-05-01T10:00:00+02:00"></time></div>
            <div class="PaidJob-inner">
                <center><img src="/banner.png" /></center>
                <center><img src="https://cdn.example.com/footer.png" /></center>
            </div>
        </div>
        """
        stash_payload = {
            "jobsearch/result_app": {
                "storeData": {
                    "results": [{"html": fragment_html}],
                    "nextPageUrl": "https://www.jobindex.dk/jobsoegning/test?page=2",
                }
            }
        }
        html_document = f"<html><body><script>var Stash = {json.dumps(stash_payload)};</script></body></html>"
        category = CategoryRecord(
            category_key="subid_1",
            category_name="subid_1",
            listing_url="https://www.jobindex.dk/jobsoegning?subid=1",
        )

        page_result = parse_jobindex_listing_page(
            html_content=html_document,
            category=category,
            page_url="https://www.jobindex.dk/jobsoegning?subid=1",
        )

        self.assertEqual(page_result.next_page_url, "https://www.jobindex.dk/jobsoegning/test?page=2")
        self.assertEqual(len(page_result.observations), 1)

        observation = page_result.observations[0]
        self.assertEqual(observation.listing_position, 1)
        self.assertEqual(observation.job_title_raw, "Senior Developer")
        self.assertEqual(observation.company_name_raw, "Example Company")
        self.assertEqual(observation.location_raw, "Odense")
        self.assertEqual(
            observation.canonical_job_url,
            "https://www.jobindex.dk/jobannonce/example-job",
        )
        self.assertEqual(observation.banner_image_url_raw, "/banner.png")
        self.assertEqual(
            observation.footer_image_url_raw,
            "https://cdn.example.com/footer.png",
        )

    def test_parse_jobindex_listing_page_requires_stash_payload(self) -> None:
        category = CategoryRecord(
            category_key="subid_1",
            category_name="subid_1",
            listing_url="https://www.jobindex.dk/jobsoegning?subid=1",
        )

        with self.assertRaises(ListingParseError):
            parse_jobindex_listing_page(
                html_content="<html><body>No stash here</body></html>",
                category=category,
                page_url="https://www.jobindex.dk/jobsoegning?subid=1",
            )

    def test_parse_jobindex_listing_page_derives_next_page_from_search_response(self) -> None:
        fragment_html = """
        <div id="jobad-wrapper-h123" data-jobsearch_position='1'>
            <h4><a href="/jobannonce/example-job">Senior Developer</a></h4>
        </div>
        """
        stash_payload = {
            "jobsearch/result_app": {
                "storeData": {
                    "results": [{"html": fragment_html}],
                    "searchResponse": {
                        "link_canonical": "https://www.jobindex.dk/jobsoegning/it/systemudvikling",
                        "total_pages": 18,
                    },
                }
            }
        }
        html_document = f"<html><body><script>var Stash = {json.dumps(stash_payload)};</script></body></html>"
        category = CategoryRecord(
            category_key="subid_1",
            category_name="subid_1",
            listing_url="https://www.jobindex.dk/jobsoegning?subid=1",
        )

        page_result = parse_jobindex_listing_page(
            html_content=html_document,
            category=category,
            page_url="https://www.jobindex.dk/jobsoegning?subid=1",
        )

        self.assertEqual(
            page_result.next_page_url,
            "https://www.jobindex.dk/jobsoegning/it/systemudvikling?page=2",
        )


if __name__ == "__main__":
    unittest.main()
