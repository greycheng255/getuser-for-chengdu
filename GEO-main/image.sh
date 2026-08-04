#!/usr/bin/env bash
# Image generation smoke test — ai6700/gpt-image-2 (model_name: gpt-image-2)
set -euo pipefail
cd "$(dirname "$0")"
source ./_env.sh

banner "image / gpt-image-2" "/v1/media/generations"

curl -sS -X POST "${ONELLM_HOST}/v1/media/generations" \
  -H "Authorization: Bearer ${ONELLM_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "一只戴眼镜的猫在图书馆里看书，油画风格",
    "size": "1024x1024",
    "n": 1
  }' | pp
