import config
import pipeline


def test_ci_run_description_only_inside_github_actions():
    """Bot runs are labelled with their GitHub Actions run link; local runs are not."""
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "ngohamah/cot_analysis",
        "GITHUB_RUN_ID": "42",
        "GITHUB_EVENT_NAME": "schedule",
    }
    assert pipeline.ci_run_description(env) == "schedule run https://github.com/ngohamah/cot_analysis/actions/runs/42"
    assert pipeline.ci_run_description({}) is None


def test_parse_args_defaults_and_flags():
    """Flags are parsed and unspecified options fall back to config.py defaults."""
    args = pipeline.parse_args(["--offline", "--start-year", "2020"])
    assert args.offline and not args.rebuild
    assert args.start_year == 2020
    assert args.data_dir == config.DATA_DIR
