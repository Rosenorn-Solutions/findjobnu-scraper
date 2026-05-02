from __future__ import annotations

import unittest
from uuid import uuid4

from jobindex_scraper.models import DetailFetchTask, ListingObservation
from jobindex_scraper.referral_stats import build_referral_stats_report


class ReferralStatsTests(unittest.TestCase):
    def test_build_referral_stats_report_supports_danish_and_non_danish_platforms(self) -> None:
        scrape_run_id = uuid4()
        observations = [
            ListingObservation(
                listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
                category_key="subid_1",
                category_name="subid_1",
                listing_position=1,
                job_url_raw="/jobannonce/a",
                canonical_job_url="https://www.jobindex.dk/jobannonce/a",
                source_host="www.jobindex.dk",
                job_title_raw="Job A",
                company_name_raw="Company A",
                company_url_raw=None,
                location_raw="Odense",
                published_raw=None,
                banner_image_url_raw=None,
                footer_image_url_raw=None,
                listing_hash="a" * 64,
            ),
            ListingObservation(
                listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1&page=2",
                category_key="subid_1",
                category_name="subid_1",
                listing_position=2,
                job_url_raw="/jobannonce/a",
                canonical_job_url="https://www.jobindex.dk/jobannonce/a",
                source_host="www.jobindex.dk",
                job_title_raw="Job A",
                company_name_raw="Company A",
                company_url_raw=None,
                location_raw="Odense",
                published_raw=None,
                banner_image_url_raw=None,
                footer_image_url_raw=None,
                listing_hash="b" * 64,
            ),
            ListingObservation(
                listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
                category_key="subid_1",
                category_name="subid_1",
                listing_position=3,
                job_url_raw="https://jobs.kk.dk/job/b",
                canonical_job_url="https://jobs.kk.dk/job/b",
                source_host="jobs.kk.dk",
                job_title_raw="Job B",
                company_name_raw="Company B",
                company_url_raw=None,
                location_raw="Kobenhavn",
                published_raw=None,
                banner_image_url_raw=None,
                footer_image_url_raw=None,
                listing_hash="c" * 64,
            ),
            ListingObservation(
                listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
                category_key="subid_1",
                category_name="subid_1",
                listing_position=4,
                job_url_raw="https://karnovgroupdenmark.teamtailor.com/job/c",
                canonical_job_url="https://karnovgroupdenmark.teamtailor.com/job/c",
                source_host="karnovgroupdenmark.teamtailor.com",
                job_title_raw="Job C",
                company_name_raw="Company C",
                company_url_raw=None,
                location_raw="Aarhus",
                published_raw=None,
                banner_image_url_raw=None,
                footer_image_url_raw=None,
                listing_hash="d" * 64,
            ),
        ]
        detail_tasks = [
            DetailFetchTask(
                scrape_run_id=scrape_run_id,
                job_id=101,
                canonical_job_url="https://www.jobindex.dk/jobannonce/a",
                source_host="www.jobindex.dk",
                category_key="subid_1",
                category_name="subid_1",
                listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
                job_title_raw="Job A",
                company_name_raw="Company A",
                company_url_raw=None,
                location_raw="Odense",
                published_raw=None,
                banner_image_url_raw=None,
                footer_image_url_raw=None,
                listing_hash="a" * 64,
                detail_refresh_reason="new",
            ),
            DetailFetchTask(
                scrape_run_id=scrape_run_id,
                job_id=102,
                canonical_job_url="https://jobs.kk.dk/job/b",
                source_host="jobs.kk.dk",
                category_key="subid_1",
                category_name="subid_1",
                listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
                job_title_raw="Job B",
                company_name_raw="Company B",
                company_url_raw=None,
                location_raw="Kobenhavn",
                published_raw=None,
                banner_image_url_raw=None,
                footer_image_url_raw=None,
                listing_hash="c" * 64,
                detail_refresh_reason="new",
            ),
        ]

        report = build_referral_stats_report(observations=observations, detail_tasks=detail_tasks, limit=10)

        self.assertEqual(report.total_unique_jobs, 3)
        self.assertEqual(report.unique_source_hosts, 3)
        self.assertEqual(report.unique_platform_domains, 3)
        self.assertEqual(report.jobindex_unique_jobs, 1)
        self.assertEqual(report.third_party_unique_jobs, 2)
        self.assertEqual(report.danish_unique_jobs, 2)
        self.assertEqual(report.danish_third_party_unique_jobs, 1)
        self.assertEqual(report.non_danish_unique_jobs, 1)
        self.assertEqual(report.non_danish_third_party_unique_jobs, 1)
        self.assertEqual(report.top_platform_domains[0].platform_domain, "jobindex.dk")
        self.assertTrue(report.top_platform_domains[0].is_jobindex_host)
        self.assertEqual(report.top_platform_domains[1].platform_domain, "kk.dk")
        self.assertTrue(report.top_platform_domains[1].is_danish_domain)
        self.assertEqual(report.top_platform_domains[2].platform_domain, "teamtailor.com")
        self.assertEqual(report.top_third_party_platform_domains[0].platform_domain, "kk.dk")
        self.assertEqual(report.top_third_party_platform_domains[1].platform_domain, "teamtailor.com")
        self.assertEqual(report.top_jobindex_source_hosts[0].source_host, "www.jobindex.dk")
        self.assertEqual(report.top_source_hosts[1].queued_detail_tasks, 1)

    def test_build_referral_stats_report_rejects_invalid_limit(self) -> None:
        with self.assertRaises(ValueError):
            build_referral_stats_report(observations=(), detail_tasks=(), limit=0)


if __name__ == "__main__":
    unittest.main()