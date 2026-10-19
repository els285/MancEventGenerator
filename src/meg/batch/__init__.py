"""Many independent replicas of one run (different seeds), locally or on a batch system.

A *campaign* is a directory holding the frozen config, the job scripts and one sub-directory per
replica. Every replica is an ordinary `meg generate` run (see job.py), so nothing about the physics
pipeline differs between one run and five thousand."""
