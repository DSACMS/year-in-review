import unittest

from scripts.filter_metrics import filter_metrics_data


class FilterMetricsDataTests(unittest.TestCase):
    def test_filters_repos_by_contributor_name(self) -> None:
        payload = {
            "repos": [
                {"name": "alpha", "contributors": [{"name": "octocat"}, {"name": "monalisa"}]},
                {"name": "beta", "contributors": [{"name": "alice"}, {"name": "bob"}]},
            ]
        }

        filtered = filter_metrics_data(payload, "octo")

        self.assertEqual([repo["name"] for repo in filtered["repos"]], ["alpha"])


if __name__ == "__main__":
    unittest.main()
