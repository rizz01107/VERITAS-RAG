"""Builds a real LaTeX (pdfTeX) two-column paper from invented text with known ground truth.

Every paragraph starts with a unique marker (MK001, MK002, ...) so reading order, page
numbers and sections can be verified against the *source*, independent of our pipeline.
"""

from __future__ import annotations

import shutil
import subprocess  # noqa: S404 - fixed argv, test-only
from dataclasses import dataclass
from pathlib import Path

_TEXT = (
    "the parameterization of representations improves interpretability and optimization "
    "while reconstruction remains difficult for efficient affine flows in first-order "
    "fine-tuning of state-of-the-art models under distributional assumptions"
)
WORDS = _TEXT.split()
LIGATURE_WORDS = ("efficient", "difficult", "affine", "flows", "first")
HYPHEN_WORDS = ("parameterization", "representations", "interpretability", "reconstruction")

TITLE = "A Synthetic Study of Efficient Low-Rank Frobnication"
HEADER = "Synthetic Running Title"


@dataclass(frozen=True)
class Marker:
    """Ground truth for one paragraph."""

    marker: str
    section: str
    reference: bool = False


def _paragraph(index: int, marker: str, n_words: int = 70) -> str:
    body = " ".join(WORDS[(index * 7 + k) % len(WORDS)] for k in range(n_words))
    return f"{marker} {body}."


def build_tex(
    paras_per_section: int = 9, twocolumn: bool = True, fontsize: int = 10
) -> tuple[str, list[Marker]]:
    """Return the LaTeX source and the ordered ground-truth markers."""
    markers: list[Marker] = []
    counter = 0

    def section_paras(section_label: str, ref: bool = False) -> str:
        nonlocal counter
        out = []
        for _ in range(paras_per_section):
            counter += 1
            marker = f"MK{counter:03d}"
            markers.append(Marker(marker, section_label, ref))
            out.append(_paragraph(counter, marker))
        return "\n\n".join(out)

    intro = section_paras("1 Introduction")
    method = section_paras("2.1 Low-Rank Update")
    exper = section_paras("3 Experiments")
    concl = section_paras("4 Conclusion")
    counter += 1
    markers.append(Marker(f"MK{counter:03d}", "References", True))
    ref_marker = f"MK{counter:03d}"
    counter += 1
    appendix_marker = f"MK{counter:03d}"
    markers.append(Marker(appendix_marker, "A Extra Details"))
    columns = ",twocolumn" if twocolumn else ""
    tex = rf"""\documentclass[{fontsize}pt{columns}]{{article}}
\usepackage[margin=0.75in]{{geometry}}
\usepackage{{amsmath,amssymb,booktabs,fancyhdr}}
\pagestyle{{fancy}}\fancyhf{{}}\fancyhead[C]{{{HEADER}}}\fancyfoot[C]{{\thepage}}
\title{{{TITLE}}}
\author{{Ada Example \and Bob Sample}}
\date{{}}
\begin{{document}}
\maketitle
\begin{{abstract}}
ABSTRACTMARK we study efficient affine flows. The first result is difficult.
\end{{abstract}}
\section{{Introduction}}
{intro}
\section{{Method}}
\subsection{{Low-Rank Update}}
{method}
\begin{{equation}}
h = W_0 x + \Delta W x, \qquad \Delta W = BA, \quad B\in\mathbb{{R}}^{{d\times r}}
\end{{equation}}
\section{{Experiments}}
{exper}
\begin{{table}}[t]
\centering
\begin{{tabular}}{{lrr}}
\toprule
Method & Params & Score \\
\midrule
alphamethod & 0.1 & 71.5 \\
betamethod & 3.6 & 88.2 \\
\bottomrule
\end{{tabular}}
\caption{{Invented results table.}}
\end{{table}}
\section{{Conclusion}}
{concl}
\begin{{thebibliography}}{{9}}
\bibitem{{a}} {ref_marker} A. Author. Invented Title One. Journal of Inventions, 2020.
\bibitem{{b}} B. Writer. Invented Title Two. Journal of Inventions, 2021.
\end{{thebibliography}}
\appendix
\section{{Extra Details}}
{appendix_marker} {" ".join(WORDS[:40])}.
\end{{document}}
"""
    return tex, markers


def compile_tex(tex: str, workdir: Path) -> Path | None:
    """Compile with pdflatex; return the PDF path or None if pdflatex is unavailable."""
    exe = shutil.which("pdflatex")
    if exe is None:
        return None
    src = workdir / "paper.tex"
    src.write_text(tex, encoding="utf-8")
    for _ in range(2):  # twice for stable layout
        subprocess.run(  # noqa: S603
            [exe, "-interaction=nonstopmode", "-halt-on-error", src.name],
            cwd=workdir,
            capture_output=True,
            check=True,
            timeout=120,
        )
    return workdir / "paper.pdf"
