#!/usr/bin/env bash
# Create AWS IoT Core things, X.509 certificates and least-privilege policies for the robot
# body (Raspberry Pi) and the brain (EC2). Run from a machine with AWS CLI v2 credentials.
#   ROBOT_ID=spider-sim AWS_REGION=ap-northeast-1 ./iot_setup.sh   # simulator robot (week 1)
#   ROBOT_ID=spider-01  AWS_REGION=ap-northeast-1 ./iot_setup.sh   # the real robot
# Output: ./certs/<robot>.{cert.pem,private.key}, spider-brain.*, AmazonRootCA1.pem, endpoint.txt
# Safe to re-run: existing things, policies and certificates are kept.
# The private keys never leave ./certs except by your own scp to the device that uses them.
set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-1}"
ROBOT_ID="${ROBOT_ID:-spider-01}"
BRAIN_ID="${BRAIN_ID:-spider-brain}"
OUT="${OUT:-./certs}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

mkdir -p "$OUT"
chmod 700 "$OUT"

render() {
  sed -e "s/__REGION__/${REGION}/g" -e "s/__ACCOUNT__/${ACCOUNT_ID}/g" \
      -e "s/__ROBOT__/${ROBOT_ID}/g" -e "s/__BRAIN__/${BRAIN_ID}/g" "$1"
}

make_thing() {  # <thing name> <policy name> <policy template>
  local name=$1 policy=$2 template=$3 arn
  aws iot describe-thing --thing-name "$name" --region "$REGION" >/dev/null 2>&1 \
    || aws iot create-thing --thing-name "$name" --region "$REGION" >/dev/null
  aws iot get-policy --policy-name "$policy" --region "$REGION" >/dev/null 2>&1 \
    || aws iot create-policy --policy-name "$policy" --region "$REGION" \
         --policy-document "$(render "$template")" >/dev/null
  if [[ -f "$OUT/$name.cert.pem" ]]; then
    echo "$name: certificate already in $OUT, not creating another one"
    return
  fi
  arn=$(aws iot create-keys-and-certificate --set-as-active --region "$REGION" \
        --certificate-pem-outfile "$OUT/$name.cert.pem" \
        --private-key-outfile "$OUT/$name.private.key" \
        --public-key-outfile "$OUT/$name.public.key" \
        --query certificateArn --output text)
  chmod 600 "$OUT/$name.private.key"
  aws iot attach-policy --policy-name "$policy" --target "$arn" --region "$REGION"
  aws iot attach-thing-principal --thing-name "$name" --principal "$arn" --region "$REGION"
  echo "$name: created certificate $arn"
}

# One body policy for the whole fleet: it uses ${iot:Connection.Thing.ThingName}, so robot N
# can only use its own topics. New robots: ROBOT_ID=spider-02 ./iot_setup.sh
make_thing "$ROBOT_ID" "SpiderBody" "$HERE/body-policy.json"
# The brain policy covers every robot (spider/*/...), like the local Mosquitto ACL.
make_thing "$BRAIN_ID" "SpiderBrain" "$HERE/brain-policy.json"

curl -fsSL -o "$OUT/AmazonRootCA1.pem" https://www.amazontrust.com/repository/AmazonRootCA1.pem
aws iot add-thing-to-thing-group --thing-group-name spider-fleet --thing-name "$ROBOT_ID" \
  --region "$REGION" 2>/dev/null || {
  aws iot create-thing-group --thing-group-name spider-fleet --region "$REGION" >/dev/null
  aws iot add-thing-to-thing-group --thing-group-name spider-fleet --thing-name "$ROBOT_ID" \
    --region "$REGION"
}
aws iot describe-endpoint --endpoint-type iot:Data-ATS --region "$REGION" \
  --query endpointAddress --output text | tee "$OUT/endpoint.txt"
echo "Done. Robot cert -> the robot (or SSM for spider-sim); brain cert -> SSM (see the plan)."
