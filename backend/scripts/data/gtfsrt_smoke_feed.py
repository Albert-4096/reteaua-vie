"""Write a tiny GTFS-RT feed that must fail validation, to check the validator runs.

Usage: gtfsrt_smoke_feed.py OUT.pb
The feed holds one alert on a stop id that no GTFS has. A working validator
loads the GTFS and reports rule E011 ("stop_id does not exist in GTFS data").
The feed carries no figure and is never published.
"""

import sys
import time

from google.transit import gtfs_realtime_pb2

UNKNOWN_STOP_ID = "smoke-test-not-a-stop"


def main() -> None:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.incrementality = gtfs_realtime_pb2.FeedHeader.FULL_DATASET
    feed.header.timestamp = int(time.time())
    entity = feed.entity.add()
    entity.id = "smoke"
    entity.alert.informed_entity.add().stop_id = UNKNOWN_STOP_ID
    header = entity.alert.header_text.translation.add()
    header.text = "smoke test"
    header.language = "en"
    with open(sys.argv[1], "wb") as f:
        f.write(feed.SerializeToString())


if __name__ == "__main__":
    main()
