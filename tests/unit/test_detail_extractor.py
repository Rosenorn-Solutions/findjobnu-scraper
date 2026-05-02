from __future__ import annotations

from datetime import datetime, timezone
import unittest
from uuid import uuid4

from jobindex_scraper.detail.extractor import GenericJobDetailExtractor
from jobindex_scraper.models import DetailFetchResult, DetailFetchTask


class GenericJobDetailExtractorTests(unittest.TestCase):
    def test_extract_result_builds_snapshot_payload_from_successful_fetch(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=101,
            canonical_job_url="https://example.com/jobs/1",
            source_host="example.com",
            category_key="subid_1",
            category_name="subid_1",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
            job_title_raw="Listing Title",
            company_name_raw="Example Company",
            company_url_raw="https://example.com",
            location_raw="Odense",
            published_raw="2026-05-02T09:00:00+02:00",
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="a" * 64,
            detail_refresh_reason="new",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=101,
            canonical_job_url="https://example.com/jobs/1",
            source_host="example.com",
            response_url="https://example.com/jobs/1",
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash="b" * 64,
            detail_refresh_reason="new",
            error_message=None,
            html_content="""
            <html>
              <head><title>Senior Platform Engineer</title></head>
              <body>
                <main>
                  <h1>Senior Platform Engineer</h1>
                  <p>Build data products for the hiring pipeline.</p>
                </main>
              </body>
            </html>
            """,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNotNone(extracted_detail)
        assert extracted_detail is not None
        self.assertEqual(extracted_detail.job_title_normalized, "Senior Platform Engineer")
        self.assertEqual(extracted_detail.company_name_normalized, "Example Company")
        self.assertEqual(extracted_detail.location_normalized, "Odense")
        self.assertEqual(extracted_detail.detail_html_hash, "b" * 64)
        self.assertEqual(extracted_detail.detail_refresh_reason, "new")
        self.assertIn("Build data products", extracted_detail.job_description_clean)
        self.assertEqual(len(extracted_detail.description_text_hash), 64)

    def test_extract_result_uses_hr_manager_container_for_clean_description(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=102,
            canonical_job_url="https://candidate.hr-manager.net/ApplicationInit.aspx?DepartmentId=18983&MediaId=59&ProjectId=147064&cid=1178",
            source_host="candidate.hr-manager.net",
            category_key="subid_1",
            category_name="subid_1",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
            job_title_raw="Listing Title",
            company_name_raw="CHANGE of Scandinavia",
            company_url_raw=None,
            location_raw="Farum",
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="c" * 64,
            detail_refresh_reason="new",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=102,
            canonical_job_url=task.canonical_job_url,
            source_host=task.source_host,
            response_url=task.canonical_job_url,
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash="d" * 64,
            detail_refresh_reason="new",
            error_message=None,
            html_content="""
            <html>
              <head><title>Talentech - Full Stack Developer – eCommerce</title></head>
              <body>
                <div class="bigbox">
                  <div class="column1">
                    <div id="AdvertisementInnerContent">
                      <p>Do you want to help shape the future eCommerce platform for Scandinavia's largest lingerie brand?</p>
                      <p><strong>About the Role</strong> As a Full Stack Developer, you will work closely with both business and technology teams.</p>
                    </div>
                  </div>
                  <div class="column2">Application due 5/29/2026 Work hours Full time 37 hours per week</div>
                </div>
              </body>
            </html>
            """,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNotNone(extracted_detail)
        assert extracted_detail is not None
        self.assertEqual(extracted_detail.job_title_normalized, "Full Stack Developer – eCommerce")
        self.assertIn("About the Role", extracted_detail.job_description_clean)
        self.assertNotIn("Application due", extracted_detail.job_description_clean)
        self.assertEqual(extracted_detail.field_provenance["job_description_clean"], "hr_manager_container")

    def test_extract_result_uses_thehub_jsonld_for_structured_content(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=103,
            canonical_job_url="https://thehub.io/jobs/69f3b50158926d41700fbb20?utm_content=dk&utm_medium=jobboard&utm_source=jobindex",
            source_host="thehub.io",
            category_key="subid_1",
            category_name="subid_1",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
            job_title_raw="Listing Title",
            company_name_raw=None,
            company_url_raw=None,
            location_raw=None,
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="e" * 64,
            detail_refresh_reason="new",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=103,
            canonical_job_url=task.canonical_job_url,
            source_host=task.source_host,
            response_url=task.canonical_job_url,
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash="f" * 64,
            detail_refresh_reason="new",
            error_message=None,
            html_content="""
            <html>
              <head>
                <title>The Hub | UI/UX Designer for early-stage SaaS startup | Orvello</title>
                <script type="application/ld+json">
                {
                  "@context": "https://schema.org/",
                  "@type": "JobPosting",
                  "title": "UI/UX Designer for early-stage SaaS startup",
                  "datePosted": "2026-04-30T20:01:05.553Z",
                  "description": "<p>We are an early-stage SaaS startup building a digital app for businesses.</p><p>You will help us turn rough ideas into a clean product experience.</p>",
                  "hiringOrganization": {"name": "Orvello"},
                  "jobLocation": {"address": {"addressLocality": "Copenhagen", "addressCountry": "Denmark"}}
                }
                </script>
              </head>
              <body>
                <section class="component-container">Visible fallback body</section>
              </body>
            </html>
            """,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNotNone(extracted_detail)
        assert extracted_detail is not None
        self.assertEqual(extracted_detail.job_title_normalized, "UI/UX Designer for early-stage SaaS startup")
        self.assertEqual(extracted_detail.company_name_normalized, "Orvello")
        self.assertEqual(extracted_detail.location_normalized, "Copenhagen, Denmark")
        self.assertIn("clean product experience", extracted_detail.job_description_clean)
        self.assertEqual(extracted_detail.field_provenance["job_description_clean"], "thehub_jsonld")
        self.assertIsNotNone(extracted_detail.published_utc)

    def test_extract_result_uses_teamtailor_jsonld_and_listing_location_fallback(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=104,
            canonical_job_url="https://karnovgroupdenmark.teamtailor.com/jobs/7669334-software-engineer",
            source_host="karnovgroupdenmark.teamtailor.com",
            category_key="subid_1",
            category_name="subid_1",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
            job_title_raw="Listing Title",
            company_name_raw=None,
            company_url_raw=None,
            location_raw="Kobenhavn K",
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="1" * 64,
            detail_refresh_reason="new",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=104,
            canonical_job_url=task.canonical_job_url,
            source_host=task.source_host,
            response_url=task.canonical_job_url,
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash="2" * 64,
            detail_refresh_reason="new",
            error_message=None,
            html_content="""
            <html>
              <head>
                <title>Software Engineer - Karnov Group</title>
                <script type="application/ld+json">
                {
                  "@context": "http://schema.org/",
                  "@type": "JobPosting",
                  "title": "Software Engineer",
                  "datePosted": "2026-05-01T00:00:00+02:00",
                  "description": "&lt;p&gt;Hi there! We are Karnov Group building AI supported research tools.&lt;/p&gt;",
                  "employmentType": "FULL_TIME",
                  "hiringOrganization": {"@type": "Organization", "name": "Karnov Group", "sameAs": "https://karnovgroupdenmark.teamtailor.com"},
                  "jobLocation": [{"@type": "Place", "address": {}}]
                }
                </script>
              </head>
              <body><h1>Software Engineer</h1></body>
            </html>
            """,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNotNone(extracted_detail)
        assert extracted_detail is not None
        self.assertEqual(extracted_detail.job_title_normalized, "Software Engineer")
        self.assertEqual(extracted_detail.company_name_normalized, "Karnov Group")
        self.assertEqual(extracted_detail.location_normalized, "Kobenhavn K")
        self.assertIn("Karnov Group", extracted_detail.job_description_clean)
        self.assertEqual(extracted_detail.field_provenance["job_description_clean"], "teamtailor_jsonld")
        self.assertEqual(extracted_detail.field_provenance["location_normalized"], "listing")

    def test_extract_result_uses_workday_jsonld_for_location_and_company(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=105,
            canonical_job_url="https://simcorp.wd3.myworkdayjobs.com/SimCorp_Jobs/job/Copenhagen/Principal-Software-Engineer_R-211612",
            source_host="simcorp.wd3.myworkdayjobs.com",
            category_key="subid_1",
            category_name="subid_1",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
            job_title_raw="Listing Title",
            company_name_raw=None,
            company_url_raw=None,
            location_raw=None,
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="3" * 64,
            detail_refresh_reason="new",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=105,
            canonical_job_url=task.canonical_job_url,
            source_host=task.source_host,
            response_url=task.canonical_job_url,
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash="4" * 64,
            detail_refresh_reason="new",
            error_message=None,
            html_content="""
            <html>
              <head>
                <meta property="og:title" content="Principal Software Engineer" />
                <script type="application/ld+json">
                {
                  "@context": "http://schema.org",
                  "@type": "JobPosting",
                  "title": "Principal Software Engineer",
                  "datePosted": "2026-04-30",
                  "description": "WHAT MAKES US, US Join some of the most innovative thinkers in FinTech.",
                  "employmentType": "FULL_TIME",
                  "hiringOrganization": {"@type": "Organization", "name": "SimCorp A/S", "sameAs": ""},
                  "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressCountry": "Denmark", "addressLocality": "Copenhagen"}}
                }
                </script>
              </head>
              <body><div id="root"></div></body>
            </html>
            """,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNotNone(extracted_detail)
        assert extracted_detail is not None
        self.assertEqual(extracted_detail.job_title_normalized, "Principal Software Engineer")
        self.assertEqual(extracted_detail.company_name_normalized, "SimCorp A/S")
        self.assertEqual(extracted_detail.location_normalized, "Copenhagen, Denmark")
        self.assertIn("innovative thinkers", extracted_detail.job_description_clean)
        self.assertEqual(extracted_detail.field_provenance["job_description_clean"], "workday_jsonld")
        self.assertEqual(extracted_detail.field_provenance["company_name_normalized"], "workday_jsonld")

    def test_extract_result_uses_emply_jobad_content_for_clean_title_and_description(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=106,
            canonical_job_url="https://ecit.career.emply.com/ad/it-projektleder-til-ecit-solutions-i-viby/6r3qmg/da",
            source_host="ecit.career.emply.com",
            category_key="subid_1",
            category_name="subid_1",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
            job_title_raw="Listing Title",
            company_name_raw="ECIT Solutions",
            company_url_raw=None,
            location_raw=None,
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="5" * 64,
            detail_refresh_reason="new",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=106,
            canonical_job_url=task.canonical_job_url,
            source_host=task.source_host,
            response_url=task.canonical_job_url,
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash="6" * 64,
            detail_refresh_reason="new",
            error_message=None,
            html_content="""
            <html>
              <head>
                <title>IT-projektleder til ECIT Solutions i Viby I Career Site</title>
                <meta property="og:title" content="IT-projektleder til ECIT Solutions i Viby I Career Site" />
              </head>
              <body>
                <header>Ledige stillinger Log ind Min profil</header>
                <div class="css_section csa_area csa_jobad">
                  <div class="css_holder">
                    <div class="csa_jobadLeft">
                      <h1 class="css_headline">IT-projektleder til ECIT Solutions i Viby</h1>
                      <div class="clear"></div>
                      <div class="csa_jobadText">
                        <p>Vil du drive komplekse leverancer for kunder og interne teams?</p>
                        <p>Du bliver ansvarlig for planlaegning, koordinering og fremdrift i vores projekter.</p>
                      </div>
                      <a class="css_button">Ansog</a>
                    </div>
                    <div class="csa_jobadRight">
                      <div class="csa_jobadInfoItem"><strong>Lokation:</strong> <span>Viby J</span></div>
                    </div>
                  </div>
                </div>
              </body>
            </html>
            """,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNotNone(extracted_detail)
        assert extracted_detail is not None
        self.assertEqual(extracted_detail.job_title_normalized, "IT-projektleder til ECIT Solutions i Viby")
        self.assertEqual(extracted_detail.company_name_normalized, "ECIT Solutions")
        self.assertEqual(extracted_detail.location_normalized, "Viby J")
        self.assertIn("komplekse leverancer", extracted_detail.job_description_clean)
        self.assertNotIn("Ledige stillinger", extracted_detail.job_description_clean)
        self.assertNotIn("Ansog", extracted_detail.job_description_clean)
        self.assertEqual(extracted_detail.field_provenance["job_description_clean"], "emply_jobad")
        self.assertEqual(extracted_detail.field_provenance["location_normalized"], "emply_jobad")

    def test_extract_result_uses_hr_on_description_container_without_leading_metadata(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=107,
            canonical_job_url="https://gomspace.hr-on.com/show-job/325809?linkref=667820&locale=en_US",
            source_host="gomspace.hr-on.com",
            category_key="subid_18",
            category_name="subid_18",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=18",
            job_title_raw="Listing Title",
            company_name_raw="GomSpace ApS",
            company_url_raw=None,
            location_raw=None,
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="7" * 64,
            detail_refresh_reason="new",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=107,
            canonical_job_url=task.canonical_job_url,
            source_host=task.source_host,
            response_url=task.canonical_job_url,
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash="8" * 64,
            detail_refresh_reason="new",
            error_message=None,
            html_content="""
            <html>
              <head>
                <title>Sales &amp; Marketing Coordinator - GomSpace</title>
                <meta property="og:title" content="Sales &amp; Marketing Coordinator" />
              </head>
              <body>
                <div id="content">
                  <div id="noxdmHeader"><h1>GomSpace</h1></div>
                  <h1>Sales &amp; Marketing Coordinator</h1>
                  <div class="job">
                    <div class="desc_column">
                      <div class="description">
                        <h4>R&amp;D Team · Odense, Denmark</h4>
                        <h4>Full-time · On-site · Reports to AI Engineering Manager</h4>
                        <p>Are you a proactive Sales &amp; Marketing Coordinator ready to turn market insight into real commercial impact?</p>
                        <h4>Your Role</h4>
                        <p>You will support sales, business development, and marketing execution across the commercial team.</p>
                      </div>
                    </div>
                    <div class="info_column">Application deadline: As soon as possible Apply</div>
                  </div>
                </div>
              </body>
            </html>
            """,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNotNone(extracted_detail)
        assert extracted_detail is not None
        self.assertEqual(extracted_detail.job_title_normalized, "Sales & Marketing Coordinator")
        self.assertEqual(extracted_detail.company_name_normalized, "GomSpace ApS")
        self.assertIn("turn market insight", extracted_detail.job_description_clean)
        self.assertIn("Your Role", extracted_detail.job_description_clean)
        self.assertNotIn("R&D Team", extracted_detail.job_description_clean)
        self.assertNotIn("Reports to AI Engineering Manager", extracted_detail.job_description_clean)
        self.assertEqual(extracted_detail.field_provenance["job_description_clean"], "hr_on_job")
        self.assertEqual(extracted_detail.field_provenance["job_title_normalized"], "hr_on_job")

    def test_extract_result_uses_signatur_content_body_without_cookie_chrome(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=108,
            canonical_job_url="https://portal.signatur.dk/ExtJobs/DefaultHosting/JobDetails.aspx?ClientId=2306&WebAdId=156436",
            source_host="portal.signatur.dk",
            category_key="subid_17",
            category_name="subid_17",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=17",
            job_title_raw="Områdeleder til Helhedsplejen Præstø",
            company_name_raw=None,
            company_url_raw=None,
            location_raw=None,
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="9" * 64,
            detail_refresh_reason="new",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=108,
            canonical_job_url=task.canonical_job_url,
            source_host=task.source_host,
            response_url=task.canonical_job_url,
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash="a" * 64,
            detail_refresh_reason="new",
            error_message=None,
            html_content="""
            <html>
              <head>
                <title>Områdeleder til Helhedsplejen Præstø – Vordingborg Kommune - Ledig stilling</title>
                <meta property="og:title" content="Områdeleder til Helhedsplejen Præstø – Vordingborg Kommune" />
              </head>
              <body>
                <form id="aspnetForm" class="main-form">
                  <a href="#main-content">Gå til sidens indhold</a>
                  <div id="main-content" class="content-outer-wrapper">
                    <div class="content-wrapper">
                      <h1 class="page-top-header special-h1-header">Vordingborg Kommune</h1>
                      <h1 id="ctl00_mainContent_contentHeadlineH1" class="content-wrapper-header with-right-menu">Områdeleder til Helhedsplejen Præstø – Vordingborg Kommune</h1>
                      <div id="ctl00_mainContent_contentBodyOuterDiv">
                        <p>Brænder du for nærværende ledelse, høj faglig kvalitet og effektiv ressourceanvendelse?</p>
                        <p>Så har du nu mulighed for at blive områdeleder i helhedsplejen i Præstø.</p>
                      </div>
                    </div>
                  </div>
                  <div id="cookieDisclaimerModalOuterDiv" class="modal">Cookies Information om cookies</div>
                </form>
              </body>
            </html>
            """,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNotNone(extracted_detail)
        assert extracted_detail is not None
        self.assertEqual(extracted_detail.job_title_normalized, "Områdeleder til Helhedsplejen Præstø")
        self.assertEqual(extracted_detail.company_name_normalized, "Vordingborg Kommune")
        self.assertIn("nærværende ledelse", extracted_detail.job_description_clean)
        self.assertNotIn("Gå til sidens indhold", extracted_detail.job_description_clean)
        self.assertNotIn("Cookies", extracted_detail.job_description_clean)
        self.assertEqual(extracted_detail.field_provenance["job_description_clean"], "signatur_page")
        self.assertEqual(extracted_detail.field_provenance["company_name_normalized"], "signatur_page")

    def test_extract_result_reuses_csa_jobad_parser_for_midtjob(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=109,
            canonical_job_url="https://midtjob.dk/ad/introduktionsstillinger-i-psykiatrien-hospitalsenhed-midt-med-mulighed-for-at-tag/wkeafp/da",
            source_host="midtjob.dk",
            category_key="subid_16",
            category_name="subid_16",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=16",
            job_title_raw="Listing Title",
            company_name_raw="Region Midtjylland",
            company_url_raw=None,
            location_raw=None,
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="b" * 64,
            detail_refresh_reason="new",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=109,
            canonical_job_url=task.canonical_job_url,
            source_host=task.source_host,
            response_url=task.canonical_job_url,
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash="c" * 64,
            detail_refresh_reason="new",
            error_message=None,
            html_content="""
            <html>
              <head>
                <title>Introduktionsstillinger i Psykiatrien Hospitalsenhed Midt med mulighed for at tage psykiatribussen til arbejde!</title>
                <meta property="og:title" content="Introduktionsstillinger i Psykiatrien Hospitalsenhed Midt med mulighed for at tage psykiatribussen til arbejde!" />
              </head>
              <body>
                <div id="body-without-popups">Startside Ledige jobs Hele Region Midtjylland</div>
                <div class="css_section csa_area csa_jobad">
                  <div class="css_holder">
                    <div class="csa_jobadLeft">
                      <h1 class="css_headline">Introduktionsstillinger i Psykiatrien Hospitalsenhed Midt med mulighed for at tage psykiatribussen til arbejde!</h1>
                      <div class="csa_jobadText">
                        <p>Søger du en introduktionsstilling, hvor du kan få lov til at behandle det hele menneske?</p>
                        <p>Ja, så har vi ledige introduktionsstillinger i Psykiatri ved HE Midt.</p>
                      </div>
                    </div>
                    <div class="csa_jobadRight">
                      <div class="csa_jobadInfoItem"><strong>Lokation:</strong> <span>Viborg</span></div>
                    </div>
                  </div>
                </div>
              </body>
            </html>
            """,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNotNone(extracted_detail)
        assert extracted_detail is not None
        self.assertEqual(
            extracted_detail.job_title_normalized,
            "Introduktionsstillinger i Psykiatrien Hospitalsenhed Midt med mulighed for at tage psykiatribussen til arbejde!",
        )
        self.assertEqual(extracted_detail.company_name_normalized, "Region Midtjylland")
        self.assertEqual(extracted_detail.location_normalized, "Viborg")
        self.assertIn("behandle det hele menneske", extracted_detail.job_description_clean)
        self.assertNotIn("Startside", extracted_detail.job_description_clean)
        self.assertEqual(extracted_detail.field_provenance["job_description_clean"], "midtjob_jobad")
        self.assertEqual(extracted_detail.field_provenance["location_normalized"], "midtjob_jobad")

    def test_extract_result_uses_graph_job_posting_for_nytlaegejob(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=110,
            canonical_job_url="https://nytlaegejob.dk/stilling/laegestilling-i-maniitsoq/",
            source_host="nytlaegejob.dk",
            category_key="subid_16",
            category_name="subid_16",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=16",
            job_title_raw="Listing Title",
            company_name_raw=None,
            company_url_raw=None,
            location_raw=None,
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="d" * 64,
            detail_refresh_reason="new",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=110,
            canonical_job_url=task.canonical_job_url,
            source_host=task.source_host,
            response_url=task.canonical_job_url,
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash="e" * 64,
            detail_refresh_reason="new",
            error_message=None,
            html_content="""
            <html>
              <head>
                <title>Lægestilling i Maniitsoq - nytlægejob.dk</title>
                <script type="application/ld+json">
                {
                  "@context": "https://schema.org",
                  "@graph": [
                    {
                      "@type": "WebPage",
                      "name": "Lægestilling i Maniitsoq"
                    },
                    {
                      "@type": "JobPosting",
                      "datePosted": "2026-05-01T15:02:05+02:00",
                      "title": "Lægestilling i Maniitsoq",
                      "description": "<p>Stillingen er ledig i perioden D. 29. juni 2026 – D. 17. august 2026.</p><p>Ansøgning bilagt kopi af relevante bilag skal sendes i PDF-format via www.gjob.dk.</p>",
                      "hiringOrganization": {
                        "@type": "Organization",
                        "name": "Det Grønlandske Sundhedsvæsen"
                      },
                      "jobLocation": {
                        "@type": "Place",
                        "address": "Det Grønlandske Sundhedsvæsen"
                      }
                    }
                  ]
                }
                </script>
              </head>
              <body>
                <header>nytlægejob.dk Danmarks største jobsite kun for lægejobs</header>
                <div class="single_job_listing">
                  <h1>Wrong fallback title</h1>
                  <ul class="job-listing-meta meta">
                    <li class="location"><a class="google_map_link">Grønland</a></li>
                    <li class="date-posted"><b>Ansøgningsfrist:</b></li>
                    <li class="job-company">Det Grønlandske Sundhedsvæsen</li>
                  </ul>
                  <div class="job-overview-content row">
                    <div class="job_listing-description job-overview">
                      <p>Stillingen er ledig i perioden D. 29. juni 2026 – D. 17. august 2026.</p>
                    </div>
                  </div>
                </div>
                <div class="related-jobs">Andre jobs der måske kunne være noget...</div>
              </body>
            </html>
            """,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNotNone(extracted_detail)
        assert extracted_detail is not None
        self.assertEqual(extracted_detail.job_title_normalized, "Lægestilling i Maniitsoq")
        self.assertEqual(extracted_detail.company_name_normalized, "Det Grønlandske Sundhedsvæsen")
        self.assertEqual(extracted_detail.location_normalized, "Grønland")
        self.assertIn("Stillingen er ledig i perioden", extracted_detail.job_description_clean)
        self.assertNotIn("Danmarks største jobsite", extracted_detail.job_description_clean)
        self.assertEqual(extracted_detail.field_provenance["job_description_clean"], "nytlaegejob_jsonld")
        self.assertEqual(extracted_detail.field_provenance["company_name_normalized"], "nytlaegejob_jsonld")
        self.assertEqual(extracted_detail.field_provenance["location_normalized"], "nytlaegejob_meta")
        self.assertIsNotNone(extracted_detail.published_utc)

    def test_extract_result_skips_unsuccessful_fetch(self) -> None:
        scrape_run_id = uuid4()
        task = DetailFetchTask(
            scrape_run_id=scrape_run_id,
            job_id=101,
            canonical_job_url="https://example.com/jobs/1",
            source_host="example.com",
            category_key="subid_1",
            category_name="subid_1",
            listing_page_url="https://www.jobindex.dk/jobsoegning?subid=1",
            job_title_raw="Listing Title",
            company_name_raw="Example Company",
            company_url_raw=None,
            location_raw=None,
            published_raw=None,
            banner_image_url_raw=None,
            footer_image_url_raw=None,
            listing_hash="a" * 64,
            detail_refresh_reason="changed",
        )
        result = DetailFetchResult(
            scrape_run_id=scrape_run_id,
            job_id=101,
            canonical_job_url="https://example.com/jobs/1",
            source_host="example.com",
            response_url=None,
            http_status=500,
            fetched_at=datetime.now(timezone.utc),
            elapsed_ms=12,
            detail_html_hash=None,
            detail_refresh_reason="changed",
            error_message="HTTP 500",
            html_content=None,
        )

        extracted_detail = GenericJobDetailExtractor().extract_result(task=task, result=result)

        self.assertIsNone(extracted_detail)


if __name__ == "__main__":
    unittest.main()