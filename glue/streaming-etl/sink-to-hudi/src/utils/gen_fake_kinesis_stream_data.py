#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
# vim: tabstop=2 shiftwidth=2 softtabstop=2 expandtab

import sys
import argparse
from datetime import datetime
import json
import random
import time

import boto3
from mimesis.locales import Locale
from mimesis.schema import Field, Schema


def main():
  parser = argparse.ArgumentParser()

  parser.add_argument('--region-name', action='store', default='us-east-1',
    help='aws region name (default: us-east-1)')
  parser.add_argument('--stream-name', help='The name of the stream to put the data record into.',
    default='hudi-demo-stream-atq4q5u')
  parser.add_argument('--max-count', default=10, type=int, help='The max number of records to put (default: 10).')
  parser.add_argument('--dry-run', action='store_true')
  parser.add_argument('--console', action='store_true', help='Print out records ingested into the stream')

  options = parser.parse_args()

  _CURRENT_YEAR = datetime.now().year

  #XXX: For more information about synthetic data schema, see
  # https://github.com/aws-samples/aws-glue-streaming-etl-blog/blob/master/config/generate_data.py
  _ = Field(locale=Locale.EN)

  _schema = Schema(schema=lambda: {
    "name": "Person{}".format(_("integer_number", start=1, end=4)),
    "date": _("formatted_date", fmt="%Y-%m-%d %H:%M:%S", start=_CURRENT_YEAR, end=_CURRENT_YEAR),
    "year": _("formatted_date", fmt="%Y", start=_CURRENT_YEAR, end=_CURRENT_YEAR),
    "month": _("formatted_date", fmt="%m", start=_CURRENT_YEAR, end=_CURRENT_YEAR),
    "day": _("formatted_date", fmt="%d", start=_CURRENT_YEAR, end=_CURRENT_YEAR),
    "column_to_update_integer": _("integer_number", start=1, end=1000000000),
    "column_to_update_string": _("choice", items=['White','Red','Yellow', 'Silver'])
  })

  if not options.dry_run:
    kinesis_streams_client = boto3.client('kinesis', region_name=options.region_name)

  cnt = 0
  for record in _schema.iterator(options.max_count):
    cnt += 1

    if options.dry_run:
      print(f"{json.dumps(record)}\n")
    else:
      res = kinesis_streams_client.put_record(
        StreamName=options.stream_name,
        Data=f"{json.dumps(record)}\n", # convert JSON to JSON Line
        PartitionKey=f"{record['name']}"
      )

      if options.console:
        print(f"{json.dumps(record)}")

      if cnt % 100 == 0:
        print(f'[INFO] {cnt} records are processed', file=sys.stderr)

      if res['ResponseMetadata']['HTTPStatusCode'] != 200:
        print(res, file=sys.stderr)
    time.sleep(random.choices([0.01, 0.03, 0.05, 0.07, 0.1])[-1])
  print(f'[INFO] Total {cnt} records are processed', file=sys.stderr)


if __name__ == '__main__':
  main()
