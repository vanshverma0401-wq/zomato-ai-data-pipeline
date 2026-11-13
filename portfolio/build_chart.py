import json
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import MultipleLocator, StrMethodFormatter


PORTFOLIO = Path(__file__).resolve().parent
OUTPUT = PORTFOLIO / "showcase"


def load_rows():
    evidence = json.loads((PORTFOLIO / "evidence" / "sql_examples.json").read_text())
    example = next(item for item in evidence["examples"] if item["question"] == "Top 10 cities by delivered GMV")
    rows = example["rows"]
    if len(rows) != 10 or len({row["CITY"] for row in rows}) != 10:
        raise ValueError("The saved result must contain ten distinct cities.")
    if any(not isinstance(row["CITY"], str) or type(row["TOTAL_GMV"]) is not int or row["TOTAL_GMV"] < 0 for row in rows):
        raise ValueError("The saved result must contain city labels and exact nonnegative integer amounts.")
    if any(rows[index]["TOTAL_GMV"] < rows[index + 1]["TOTAL_GMV"] for index in range(9)):
        raise ValueError("The saved result must retain its descending GMV order.")
    return rows


def main():
    rows = load_rows()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    matplotlib.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none"})
    background = "#f1f5f9"
    ink = "#142d3b"
    muted = "#4a6172"
    values = [row["TOTAL_GMV"] for row in rows]
    cities = [row["CITY"] for row in rows]
    scaled = [value / 1000000 for value in values]
    palette = LinearSegmentedColormap.from_list("teal_blue", ["#087f8c", "#507fb5"])
    colors = [palette(index / 12) for index in range(len(rows))]
    figure, axes = plt.subplots(figsize=(16, 10), dpi=100)
    figure.set_facecolor(background)
    figure.subplots_adjust(left=0.17, right=0.94, top=0.78, bottom=0.21)
    axes.set_facecolor(background)
    bars = axes.barh(range(len(rows)), scaled, height=0.66, color=colors, zorder=3)
    axes.set_yticks(range(len(rows)), labels=cities)
    axes.invert_yaxis()
    axes.set_xlim(0, max(scaled) * 1.28)
    axes.xaxis.set_major_locator(MultipleLocator(100))
    axes.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    axes.tick_params(axis="y", length=0, pad=14, labelsize=16, colors=ink)
    axes.tick_params(axis="x", length=0, pad=10, labelsize=12, colors=muted)
    axes.grid(axis="x", color="#d7e1e9", linewidth=0.9, zorder=0)
    axes.set_axisbelow(True)
    axes.set_xlabel("Recorded source units (millions on axis)", fontsize=13, color=muted, labelpad=17)
    for spine in axes.spines.values():
        spine.set_visible(False)
    for bar, value in zip(bars, values):
        axes.annotate(
            f"{value:,}",
            xy=(bar.get_width(), bar.get_y() + bar.get_height() / 2),
            xytext=(10, 0),
            textcoords="offset points",
            va="center",
            fontsize=14,
            color=ink,
            fontweight="normal",
        )
    figure.text(0.065, 0.935, "Delivered GMV by city", fontsize=32, fontweight="bold", color=ink, va="top")
    figure.text(0.065, 0.866, "Top 10 cities from the saved warehouse-app result", fontsize=17, color=muted, va="top")
    figure.text(0.065, 0.825, "Recorded delivered sales amount · exact values shown · not profit", fontsize=13, color=muted, va="top")
    figure.text(0.065, 0.105, "SAVED UI RESULT · 13 NOVEMBER 2026 · TUTORIAL-GENERATED DATA", fontsize=11, fontweight="bold", color="#087f8c")
    figure.text(0.065, 0.061, "Rendered from retained results, not a live application. No new model or warehouse call was used to create this chart.", fontsize=11, color=muted)
    title = "Delivered GMV by city"
    description = "Ten exact city totals from the saved November 13, 2026 tutorial-generated result. Recorded source units, not profit; rendered evidence, not a live app."
    png = OUTPUT / "gmv-delivered-cities.png"
    svg = OUTPUT / "gmv-delivered-cities.svg"
    figure.savefig(png, dpi=100, facecolor=background, metadata={"Title": title, "Description": description, "Software": "Matplotlib"})
    figure.savefig(svg, facecolor=background, metadata={"Title": title, "Description": description, "Creator": "Matplotlib"})
    plt.close(figure)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    tree = ET.parse(svg)
    tree.getroot().set("width", "1600")
    tree.getroot().set("height", "1000")
    tree.write(svg, encoding="utf-8", xml_declaration=True)
    print(json.dumps({"matplotlib_version": matplotlib.__version__, "rows": len(rows), "width": 1600, "height": 1000, "png": png.name, "svg": svg.name}))


if __name__ == "__main__":
    main()
