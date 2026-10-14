from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure


def assemble_pdf(figures: Iterable[Figure], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(output_path) as pdf:
        for fig in figures:
            pdf.savefig(fig, dpi=300)
            plt.close(fig)
