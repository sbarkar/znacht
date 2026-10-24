# Znacht add-on (HAOS)

Packaging of the same engine image for Home Assistant OS, for households without a separate host. Add this repository as an add-on repository in HA, install "Znacht", fill in the options, start it, then add the Znacht integration pointing at `http://<host>:8787` (or the ingress URL) with the same API token.

The LXC deployment in `deploy/` is the primary path; this add-on is the same image with a Supervisor-aware entrypoint.
