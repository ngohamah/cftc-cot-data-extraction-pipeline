import config
import pipeline


def test_parse_args_defaults_and_flags():
    args = pipeline.parse_args(["--offline", "--start-year", "2020"])
    assert args.offline and not args.rebuild
    assert args.start_year == 2020
    assert args.data_dir == config.DATA_DIR
