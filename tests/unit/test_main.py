from __future__ import annotations

from contextlib import redirect_stdout
import io
import unittest

from jobindex_scraper.main import _build_referral_summary, _print_results, build_argument_parser
from jobindex_scraper.referral_stats import ReferralHostStat, ReferralPlatformStat, ReferralStatsReport


class MainTests(unittest.TestCase):
    def test_argument_parser_accepts_referral_stats_flags(self) -> None:
        args = build_argument_parser().parse_args(
            [
                "--subid",
                "1",
                "--dump-referral-stats",
                "--referral-stats-limit",
                "25",
            ]
        )

        self.assertTrue(args.dump_referral_stats)
        self.assertEqual(args.referral_stats_limit, 25)

    def test_build_referral_summary_returns_flat_counts(self) -> None:
        report = ReferralStatsReport(
            total_unique_jobs=12,
            unique_source_hosts=5,
            unique_platform_domains=4,
            jobindex_unique_jobs=6,
            third_party_unique_jobs=6,
            danish_unique_jobs=8,
            danish_third_party_unique_jobs=2,
            non_danish_unique_jobs=4,
            non_danish_third_party_unique_jobs=4,
            top_source_hosts=(),
            top_jobindex_source_hosts=(),
            top_platform_domains=(),
            top_third_party_platform_domains=(),
        )

        summary = _build_referral_summary(report)

        self.assertEqual(summary["referral_jobindex_jobs"], 6)
        self.assertEqual(summary["referral_third_party_jobs"], 6)
        self.assertEqual(summary["referral_danish_jobs"], 8)
        self.assertEqual(summary["referral_danish_third_party_jobs"], 2)
        self.assertEqual(summary["referral_non_danish_jobs"], 4)
        self.assertEqual(summary["referral_non_danish_third_party_jobs"], 4)

    def test_print_results_includes_referral_stats_dump(self) -> None:
        report = ReferralStatsReport(
            total_unique_jobs=3,
            unique_source_hosts=2,
            unique_platform_domains=2,
            jobindex_unique_jobs=1,
            third_party_unique_jobs=2,
            danish_unique_jobs=1,
            danish_third_party_unique_jobs=0,
            non_danish_unique_jobs=2,
            non_danish_third_party_unique_jobs=2,
            top_source_hosts=(
                ReferralHostStat(
                    source_host="www.jobindex.dk",
                    platform_domain="jobindex.dk",
                    unique_jobs=1,
                    queued_detail_tasks=1,
                    is_jobindex_host=True,
                    is_danish_domain=True,
                ),
            ),
            top_jobindex_source_hosts=(
                ReferralHostStat(
                    source_host="www.jobindex.dk",
                    platform_domain="jobindex.dk",
                    unique_jobs=1,
                    queued_detail_tasks=1,
                    is_jobindex_host=True,
                    is_danish_domain=True,
                ),
            ),
            top_platform_domains=(
                ReferralPlatformStat(
                    platform_domain="jobindex.dk",
                    unique_jobs=1,
                    unique_hosts=1,
                    queued_detail_tasks=1,
                    is_jobindex_host=True,
                    is_danish_domain=True,
                ),
            ),
            top_third_party_platform_domains=(
                ReferralPlatformStat(
                    platform_domain="teamtailor.com",
                    unique_jobs=2,
                    unique_hosts=1,
                    queued_detail_tasks=2,
                    is_jobindex_host=False,
                    is_danish_domain=False,
                ),
            ),
        )
        output = io.StringIO()

        with redirect_stdout(output):
            _print_results(
                summary={"category_key": "subid_1"},
                observations=[],
                detail_tasks=[],
                detail_results=[],
                referral_stats=report,
                dump_observations=False,
                dump_detail_tasks=False,
                dump_detail_results=False,
                dump_referral_stats=True,
            )

        text = output.getvalue()
        self.assertIn('"category_key": "subid_1"', text)
        self.assertIn('"top_platform_domains"', text)
        self.assertIn('"top_third_party_platform_domains"', text)
        self.assertIn('"jobindex.dk"', text)


if __name__ == "__main__":
    unittest.main()