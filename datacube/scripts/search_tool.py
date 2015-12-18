#!/usr/bin/env python
# coding=utf-8
"""
Query datasets and storage units.
"""
from __future__ import absolute_import
from __future__ import print_function

import csv
import datetime
import sys
from functools import partial

import click
from dateutil import tz
from psycopg2._range import Range
from singledispatch import singledispatch

from datacube import ui

CLICK_SETTINGS = dict(help_option_names=['-h', '--help'])


def printable_values(d):
    return {k: printable(v) for k, v in d.items()}


def write_pretty(out_f, fields, search_results, terminal_size=click.get_terminal_size()):
    """
    Output in a human-readable text format. Inspired by psql's expanded output.
    """
    terminal_width = terminal_size[0]
    record_num = 1

    field_header_width = max([len(field_name) for field_name in fields])
    field_output_format = '{:<' + str(field_header_width) + '} | {}'

    for result in search_results:
        separator_line = '-[ {} ]'.format(record_num)
        separator_line += '-' * (terminal_width - len(separator_line) - 1)
        click.echo(separator_line, file=out_f)

        for name, value in sorted(result.items()):
            click.echo(
                field_output_format.format(name, printable(value)),
                file=out_f
            )

        record_num += 1


def write_csv(out_f, fields, search_results):
    """
    Output as a CSV.
    """
    writer = csv.DictWriter(out_f, tuple(sorted(fields.keys())))
    writer.writeheader()
    writer.writerows(
        (
            printable_values(d) for d in
            search_results
        )
    )


OUTPUT_FORMATS = {
    'csv': write_csv,
    'pretty': write_pretty
}


@click.group(help="Search the Data Cube", context_settings=CLICK_SETTINGS)
@ui.global_cli_options
@click.option('-f',
              type=click.Choice(OUTPUT_FORMATS.keys()),
              default='pretty', show_default=True,
              help='Output format')
@click.pass_context
def cli(ctx, f):
    ctx.obj['write_results'] = partial(OUTPUT_FORMATS[f], sys.stdout)


@cli.command(help='Datasets')
@click.argument('expression', nargs=-1)
@ui.pass_index
@click.pass_context
def datasets(ctx, index, expression):
    ctx.obj['write_results'](
        index.datasets.get_fields(),
        index.datasets.search_summaries(*ui.parse_expressions(index.datasets.get_field, *expression))
    )


@cli.command(help='Storage units')
@click.argument('expression', nargs=-1)
@ui.pass_index
@click.pass_context
def units(ctx, index, expression):
    ctx.obj['write_results'](
        index.storage.get_fields(),
        index.storage.search_summaries(*ui.parse_expressions(index.storage.get_field_with_fallback, *expression))
    )


@singledispatch
def printable(val):
    return val


@printable.register(type(None))
def printable_none(val):
    return ''


@printable.register(datetime.datetime)
def printable_dt(val):
    """
    :type val: datetime.datetime
    """
    # Default to UTC.
    if val.tzinfo is None:
        return val.replace(tzinfo=tz.tzutc()).isoformat()
    else:
        return val.astimezone(tz.tzutc()).isoformat()


@printable.register(Range)
def printable_r(val):
    """
    :type val: psycopg2._range.Range
    """
    if val.lower_inf:
        return printable(val.upper)
    if val.upper_inf:
        return printable(val.lower)

    return '{} to {}'.format(printable(val.lower), printable(val.upper))


if __name__ == '__main__':
    cli()
