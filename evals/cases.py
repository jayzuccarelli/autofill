"""Ground-truth facts each fixture profile contains.

One ``Case`` is one thing a form might ask for.  ``pattern`` is a regex
matched against the retrieved context after whitespace is collapsed to
single spaces, so patterns can be written as if the source were unwrapped.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    fixture: str
    field: str
    pattern: str


CASES: list[Case] = [
    # ---------------------------------------------------------------- minimal
    Case("minimal", "Email", r"dana\.okonkwo@example\.com"),
    Case("minimal", "Phone", r"\+1 \(415\) 555-0182"),
    Case("minimal", "City", r"Oakland"),
    Case("minimal", "State", r"California"),
    Case("minimal", "Years of experience", r"six years of experience"),
    Case("minimal", "Primary languages", r"Go and Python"),
    Case("minimal", "Work authorization", r"United States citizen"),
    Case("minimal", "Sponsorship required", r"No sponsorship required"),
    # --------------------------------------------------------------- standard
    Case("standard", "Email", r"priya\.raghunathan@example\.com"),
    Case("standard", "Phone", r"\+1 \(206\) 555-0143"),
    Case("standard", "City", r"Seattle"),
    Case("standard", "LinkedIn URL", r"linkedin\.com/in/priya-raghunathan-example"),
    Case("standard", "GitHub URL", r"github\.com/praghunathan-example"),
    Case("standard", "Portfolio URL", r"priyabuilds\.example\.com"),
    Case("standard", "Years of experience", r"nine years of experience"),
    Case("standard", "Work authorization", r"permanent resident"),
    Case("standard", "Sponsorship required", r"[Nn]ot requiring visa sponsorship"),
    Case("standard", "Highest degree", r"Master of Science in Computer Science"),
    Case("standard", "Graduate school", r"University of Washington"),
    Case("standard", "Graduate GPA", r"GPA 3\.87"),
    Case("standard", "Undergraduate school", r"Birla Institute of Technology"),
    Case("standard", "Current employer", r"Nordhaven Commerce"),
    Case("standard", "Current title", r"Staff Machine Learning Engineer"),
    Case("standard", "Current start date", r"March 2021"),
    Case("standard", "Previous employer", r"Kestrel Labs"),
    Case("standard", "Earliest employer", r"Talus Analytics"),
    Case("standard", "Skills", r"PyTorch"),
    Case("standard", "Languages spoken", r"Tamil"),
    Case("standard", "Certifications", r"AWS Certified Machine Learning Specialty"),
    Case("standard", "Current salary", r"265,000"),
    Case("standard", "Expected salary", r"300,000"),
    Case("standard", "Gender", r"Gender: female"),
    Case("standard", "Veteran status", r"not a veteran"),
    Case("standard", "Disability status", r"no disability"),
    Case("standard", "Notice period", r"Four weeks"),
    # ------------------------------------------------------------------- long
    Case("long", "Email", r"marcus\.thorvaldsen@example\.com"),
    Case("long", "Phone", r"\+1 \(617\) 555-0119"),
    Case("long", "City", r"Cambridge"),
    Case("long", "LinkedIn URL", r"linkedin\.com/in/marcus-thorvaldsen-example"),
    Case("long", "GitHub URL", r"github\.com/mthorvaldsen-example"),
    Case("long", "Years of experience", r"eighteen years"),
    Case("long", "Work authorization", r"Dual citizen"),
    Case("long", "Sponsorship required", r"without sponsorship"),
    Case("long", "Highest degree", r"Doctor of Philosophy"),
    Case("long", "Doctoral school", r"Massachusetts Institute of Technology"),
    Case("long", "Undergraduate school", r"Norwegian University of Science"),
    Case("long", "Current employer", r"Halberd Data"),
    Case("long", "Current title", r"Vice President of Engineering"),
    Case("long", "Current start date", r"September 2021"),
    Case("long", "Team size managed", r"78-person"),
    Case("long", "Previous employer", r"Quill Systems"),
    Case("long", "Earliest employer", r"Corvid Storage"),
    Case("long", "Skills", r"TLA\+"),
    Case("long", "Open source", r"leader election"),
    Case("long", "Publications", r"peer-reviewed papers"),
    Case("long", "Patents", r"Three granted United States patents"),
    Case("long", "Languages spoken", r"Norwegian \(native\)"),
    Case("long", "Certifications", r"Certified Kubernetes Administrator"),
    Case("long", "Military service", r"Norwegian military service"),
    Case("long", "Volunteer work", r"refurbished laptops"),
    Case("long", "Current salary", r"640,000"),
    Case("long", "Expected salary", r"420,000"),
    Case("long", "Gender", r"Gender: male"),
    Case("long", "Veteran status", r"not a protected veteran"),
    Case("long", "Disability status", r"no disability"),
    Case("long", "Notice period", r"Eight weeks"),
    Case("long", "Relocation", r"Open to relocation"),
    Case("long", "How did you hear about us", r"Referred by a former colleague"),
]


def fixtures() -> list[str]:
    """Fixture names in the order they first appear in ``CASES``."""
    seen: list[str] = []
    for case in CASES:
        if case.fixture not in seen:
            seen.append(case.fixture)
    return seen
