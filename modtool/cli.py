#!/usr/bin/env python3
"""
modtool — DC Server Module Analysis Tool

Usage
-----
  modtool fetch all                          Fetch modules from all servers
  modtool fetch server <IP>                  Fetch from one server
  modtool fetch filter [--server-type ...]   Fetch from a filtered subset

  modtool show server <IP>                   All modules for one server
  modtool show servers [--server-type ...]   List servers with module counts
  modtool show module <MODULE>               Which servers have this module
  modtool show analyze common [--service ...] Common/default modules
  modtool show analyze exclusive [...]       Modules exclusive to a category
  modtool show analyze compare [...]         Compare two categories
  modtool show analyze matrix [--by ...]     Module-presence matrix

  modtool stats summary                      DC-wide overview
  modtool stats coverage                     Fetch coverage
  modtool stats by-type                      Stats per server type
  modtool stats by-service                   Stats per ZService
  modtool stats by-component                 Stats per Component
  modtool stats by-group                     Stats per Group
  modtool stats top-modules [-n N]           N most prevalent modules
  modtool stats rare-modules [-n N]          N rarest modules

  modtool ip list [--reason ...]             List tracked failure IPs
  modtool ip add <IP> --reason ...           Add an IP
  modtool ip remove <IP>                     Remove an IP
  modtool ip bulk-add <FILE> --reason ...    Bulk-add from a text file
  modtool ip classify [--from-dir ...]       Import from legacy txt files
  modtool ip retry [--reason ...]            Show retryable IPs
  modtool ip clear [--reason ...]            Clear tracked IPs
  modtool ip stats                           Count by reason
"""

import sys
import os

# Ensure the modtool package root is on PYTHONPATH when run as a script
sys.path.insert(0, os.path.dirname(__file__))

import click

from fetch.fetch_modules import fetch_group
from display.show_modules import show_group
from display.show_stats import stats_group
from ip_manager.ip_manager import ip_group


@click.group()
@click.version_option(version="1.0.0", prog_name="modtool")
def cli():
    """
    modtool — Kernel module analysis tool for the DC server fleet.

    Fetch lsmod data from servers, then analyze and compare module sets
    across server types, ZServices, Components, and Groups.
    """
    pass


cli.add_command(fetch_group, name="fetch")
cli.add_command(show_group, name="show")
cli.add_command(stats_group, name="stats")
cli.add_command(ip_group, name="ip")


if __name__ == "__main__":
    cli()
