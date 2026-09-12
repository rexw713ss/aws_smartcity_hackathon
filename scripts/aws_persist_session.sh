#!/usr/bin/env bash
# Persist the AWS credentials already exported in THIS shell into ~/.aws so that
# tools started from a fresh shell (the test suite, uvicorn, an agent session)
# can see them through the standard boto3 credential chain.
#
# No secret is written by, or passed through, anything but your own shell: the
# values are read from the environment variables you already exported.
#
#   export AWS_ACCESS_KEY_ID=...      # already done
#   export AWS_SECRET_ACCESS_KEY=...  # already done
#   export AWS_SESSION_TOKEN=...      # already done (temporary credentials)
#   ./scripts/aws_persist_session.sh
set -euo pipefail

PROFILE="${1:-default}"
REGION="${AWS_DEFAULT_REGION:-${AWS_REGION:-us-east-1}}"

for name in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
  if [ -z "${!name:-}" ]; then
    echo "error: \$$name is not set in this shell." >&2
    echo "Export your credentials here first, then re-run this script." >&2
    exit 1
  fi
done

aws configure set aws_access_key_id     "$AWS_ACCESS_KEY_ID"     --profile "$PROFILE"
aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY" --profile "$PROFILE"
if [ -n "${AWS_SESSION_TOKEN:-}" ]; then
  aws configure set aws_session_token   "$AWS_SESSION_TOKEN"     --profile "$PROFILE"
fi
aws configure set region "$REGION" --profile "$PROFILE"

chmod 600 "${HOME}/.aws/credentials" 2>/dev/null || true

echo "Wrote profile '$PROFILE' (region $REGION) to ~/.aws/credentials."
if [ -n "${AWS_SESSION_TOKEN:-}" ]; then
  echo "These are temporary credentials; re-run this script after they expire."
fi
echo
echo "Verify:"
echo "  aws sts get-caller-identity"
