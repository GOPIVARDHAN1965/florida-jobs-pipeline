from scrape import parse_salary

# real strings from jobs.myflorida.com
CASES = {
    "$93,967.40 Annually": (93967, 93967),
    "$50,000.08 annually / $1,923.08 bi-weekly": (50000, 50000),
    "$1,953.15 - $2,249.52 Biweekly": (50782, 58488),
    "$3,945.84 monthly; $47,350.08 annually": (47350, 47350),
    "$24.00-$35.00": (49920, 72800),
    "23.38 hourly": (48630, 48630),
    "$45,060.11 to $48,000 annually; commensurate with education and experience.": (45060, 48000),
    "$46,583.04 plus $1,268.76 Competitive Area Differential (CAD) / annually": (46583, 46583),
    "$1,576.92 Biweekly + benefits": (41000, 41000),
    "$1,392.96 bi-weekly, $36, 216.96 annually": (36217, 36217),
    "$1,424.46 Biweekly or 10% increase if promotion": (37036, 37036),
    "0-3.9yrs=$2,299.04; 4-6.9yrs=$2,412.05; 7-9.9yrs=$2,457.42; 10+yrs=$2,525.06 Biweekly": (59775, 65652),
    "$ 42,561.48- $47,2350.16 Annually": (42561, 42561),
    "agency to update": (None, None),
    "Negotiable": (None, None),
}

for raw, want in CASES.items():
    got = parse_salary(raw)
    assert got == want, f"{raw!r}: got {got}, want {want}"
print(f"ok: {len(CASES)} salary cases")
