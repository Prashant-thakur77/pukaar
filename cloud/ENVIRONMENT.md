# Cloud environment settings

Enter these in the Claude Code cloud environment for this repository.

## Network access

Choose **Custom**, keep **Include default allowed domains** checked, and add:

```
api.open-meteo.com
flood-api.open-meteo.com
archive-api.open-meteo.com
geocoding-api.open-meteo.com
api.telegram.org
*.amplifyapp.com
ecolafaek.com
*.ecolafaek.com
tile.openstreetmap.org
```

The AWS CLI, SAM and the Bedrock, Polly and Transcribe clients call
`*.amazonaws.com`. If those calls fail with a proxy or 403 error, add
`*.amazonaws.com` to the list above (PLAN.md section 1 says to record such a
host under "Needs human" in PROGRESS.md rather than work around it).

## Environment variables

```
AWS_ACCESS_KEY_ID=<access key id of the pukaar-cloud IAM user>
AWS_SECRET_ACCESS_KEY=<its secret access key>
AWS_DEFAULT_REGION=us-east-1
```

Take the two key values from `.cloud-keys.local` on the machine that created
the IAM user. That file is git-ignored; never commit the values or paste them
into chat.

## Setup script

```
bash cloud/setup.sh
```

It installs the AWS CLI and SAM CLI (with pip, falling back to
`--break-system-packages` on an externally managed Python), the backend dev
dependencies from `backend/uv.lock`, and the frontend dependencies from
`frontend/package-lock.json`, in parallel. A clean run took about 25 seconds.
Logs go to `$TMPDIR/pukaar-setup/`. The script fails only if the backend or
frontend install fails.
