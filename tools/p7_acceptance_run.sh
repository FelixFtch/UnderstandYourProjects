#!/bin/bash
# P7: 创建并运行 durable IndexJob (全部环境与 uyp-indexjob.service 一致)
cd /home/jetson/dev/uyp/indexer
env UYP_STATE_ROOT=/home/jetson/dev/uyp/state \
    UYP_OUTPUT_ROOT=/home/jetson/dev/uyp/output \
    UYP_HOMEHUB_ACCESS_CONTEXT_URL=http://127.0.0.1:5120/api/uyp/access-context \
    UYP_HOMEHUB_TOKEN_FILE=/home/jetson/.config/uyp/homehub.token \
    /usr/bin/python3 index_job.py \
    --state-root /home/jetson/dev/uyp/state \
    --output-root /home/jetson/dev/uyp/output \
    --access-context /home/jetson/.config/uyp/access-context.json \
    --connector-host http://127.0.0.1:7121 \
    --token-file /home/jetson/.config/uyp/token \
    --ua-root /home/jetson/dev/uyp/understand-anything-src-20261009 \
    create --project-id jarvis-memory-live \
           --source-id connector:jarvis-memory-live \
           --connector-grant-id g_ab13bf8a \
           --total 120 --limit 0
echo "--- run-pending (前台, 全程) ---"
env UYP_STATE_ROOT=/home/jetson/dev/uyp/state \
    UYP_OUTPUT_ROOT=/home/jetson/dev/uyp/output \
    UYP_HOMEHUB_ACCESS_CONTEXT_URL=http://127.0.0.1:5120/api/uyp/access-context \
    UYP_HOMEHUB_TOKEN_FILE=/home/jetson/.config/uyp/homehub.token \
    /usr/bin/python3 index_job.py \
    --state-root /home/jetson/dev/uyp/state \
    --output-root /home/jetson/dev/uyp/output \
    --access-context /home/jetson/.config/uyp/access-context.json \
    --connector-host http://127.0.0.1:7121 \
    --token-file /home/jetson/.config/uyp/token \
    --ua-root /home/jetson/dev/uyp/understand-anything-src-20261009 \
    run-pending --max-jobs 1
