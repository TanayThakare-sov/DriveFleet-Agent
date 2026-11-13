"""Generate fictional sample datasheets (Markdown) into data/datasheets/.

These stand in for the real PDFs/pages you indexed in Project 2. Numbers here must stay
consistent with MODELS in src/drivefleet/seed.py (tests/test_datasheet_tool.py checks this).
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "datasheets"

# name: (slug, capacity_tb, interface, rpm, warranty_months, cache_mb, mtbf, afr, workload_tb_yr,
#        max_temp_c, idle_w, active_w, helium, speed_mb_s, notes)
SPECS = {
    "Orion O12": ("orion-o12", 12, "SATA 6 Gb/s", 7200, 60, 256, 2_500_000, 0.35, 550, 60, 5.0, 8.5, False, 250,
                  "General-purpose enterprise capacity drive for cloud storage and backup."),
    "Orion O16": ("orion-o16", 16, "SATA 6 Gb/s", 7200, 60, 256, 2_500_000, 0.35, 550, 60, 5.2, 9.0, False, 260,
                  "Higher-capacity member of the Orion family for scale-out object storage."),
    "Vega V8": ("vega-v8", 8, "SAS 12 Gb/s", 7200, 36, 256, 2_000_000, 0.44, 550, 60, 6.0, 9.5, False, 230,
                "Dual-port SAS drive for enterprise arrays that need multipath redundancy."),
    "Vega V10": ("vega-v10", 10, "SAS 12 Gb/s", 7200, 48, 256, 2_000_000, 0.44, 550, 60, 6.1, 9.8, False, 240,
                 "Dual-port SAS drive with higher capacity for tiered enterprise storage."),
    "Atlas A20": ("atlas-a20", 20, "SATA 6 Gb/s", 7200, 60, 512, 2_500_000, 0.35, 550, 65, 4.6, 7.4, True, 285,
                  "Helium-sealed high-capacity drive for hyperscale and data-lake deployments."),
    "Nova N4": ("nova-n4", 4, "SATA 6 Gb/s", 5400, 24, 64, 1_000_000, 0.87, 180, 55, 3.4, 5.0, False, 150,
                "Entry-level drive for small servers, NAS and surveillance recorders."),
}


def render(name, s):
    (_, cap, iface, rpm, warr, cache, mtbf, afr, workload, tmax, idle, active, helium, speed, notes) = s
    fill = "helium-sealed" if helium else "air-filled"
    return f"""# {name} Datasheet
Document: DS-{name.upper().replace(' ', '-')} Rev B

## Overview
The {name} is a {cap} TB, 3.5-inch, {fill} {iface.split()[0]} hard drive. {notes}

## Specifications
- Capacity: {cap} TB
- Interface: {iface}
- Spindle speed: {rpm} RPM
- Cache: {cache} MB
- Sustained transfer rate: up to {speed} MB/s
- Form factor: 3.5-inch
- Construction: {fill}{" (helium)" if helium else ""}

## Reliability
- MTBF: {mtbf:,} hours
- Annualized failure rate (AFR): {afr}%
- Workload rate: {workload} TB/year
- Non-recoverable read errors per bits read: 1 in 10^15

## Power and Environmental
- Idle power: {idle} W
- Active (random read/write) power: {active} W
- Operating temperature: 5 °C to {tmax} °C
- Non-operating temperature: -40 °C to 70 °C
- Operating shock (2 ms): 70 G

## Warranty
The {name} carries a limited warranty of {warr} months ({warr // 12} years) from the date of
purchase. The warranty covers defects in materials and workmanship under normal use within the
rated workload of {workload} TB/year. Drives operated above the rated workload or outside the
operating temperature range may be excluded from warranty coverage.

## Support
Firmware updates and replacement requests are handled through the enterprise support portal.
Advance replacement is available for the duration of the warranty period.
"""


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, spec in SPECS.items():
        (OUT / f"{spec[0]}.md").write_text(render(name, spec), encoding="utf-8")
    print(f"Wrote {len(SPECS)} datasheets to {OUT}")
