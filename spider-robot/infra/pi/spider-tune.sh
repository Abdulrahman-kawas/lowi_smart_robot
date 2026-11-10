#!/usr/bin/env bash
# Keeps kernel work off core 0 and CPU frequency steady. Safe to run repeatedly.
# Prints what it could not move; the bench gate decides whether that matters.
set -uo pipefail

echo e > /proc/irq/default_smp_affinity   # new interrupts avoid core 0

route() {  # <pattern in /proc/interrupts> <cpu mask>
  local pattern=$1 mask=$2 irq
  grep -E "$pattern" /proc/interrupts | cut -d: -f1 | tr -d ' ' | while read -r irq; do
    if ! echo "$mask" > "/proc/irq/$irq/smp_affinity" 2>/dev/null; then
      echo "spider-tune: could not move IRQ $irq ($pattern)"
    fi
  done
}

for dir in /proc/irq/[0-9]*; do
  echo e > "$dir/smp_affinity" 2>/dev/null || true
done
route 'eth0' 2          # LiDAR traffic: core 1
route 'xhci|usb|pcie' 4 # servo controller, microphone, speaker: core 2
route 'mmc|wlan' 8      # SD card and Wi-Fi: core 3

for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  echo performance > "$gov"
done

echo "spider-tune: IRQs on core 0 after tuning:"
awk 'NR>1 && $2+0 > 0 {print "  " $0}' /proc/interrupts | head -20
