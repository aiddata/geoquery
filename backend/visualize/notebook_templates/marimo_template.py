# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "geopandas", "pandas", "matplotlib"]
# ///
import marimo

__generated_with = "0.13.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    mo.md(
        """
        # GeoQuery Results — {{REQUEST_NAME}}

        **Request ID:** `{{REQUEST_ID}}`
        **Generated:** {{DATE}}

        Run the cells below to download your results and start exploring.
        """
    )
    return


# ── 1. Download & extract ────────────────────────────────────────────────────


@app.cell
def _():
    import pathlib
    import urllib.request
    import zipfile

    DOWNLOAD_URL = "{{DOWNLOAD_URL}}"
    OUT = pathlib.Path("geoquery_results")
    OUT.mkdir(exist_ok=True)

    zip_path = OUT / "results.zip"
    urllib.request.urlretrieve(DOWNLOAD_URL, zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(OUT)

    files = sorted(f for f in OUT.rglob("*") if f.is_file() and f.suffix != ".zip")
    return OUT, DOWNLOAD_URL, files, zip_path


@app.cell
def _(files, mo):
    mo.md("### Extracted files\n" + "\n".join(f"- `{f}`" for f in files))
    return


# ── 2. Tabular results (CSV) ─────────────────────────────────────────────────


@app.cell
def _(OUT):
    import pandas as pd

    csv_files = sorted(OUT.rglob("*.csv"))
    df = pd.read_csv(csv_files[0])
    return (df,)


@app.cell
def _(df):
    df
    return


@app.cell
def _(df):
    df.describe()
    return


# ── 3. Spatial data (GeoPackage) ─────────────────────────────────────────────


@app.cell
def _(OUT):
    import geopandas as gpd

    gpkg_files = sorted(OUT.rglob("*.gpkg"))
    gdf = gpd.read_file(gpkg_files[0])
    return (gdf,)


@app.cell
def _(gdf):
    gdf.head()
    return


# ── 4. Join CSV to spatial data ───────────────────────────────────────────────


@app.cell
def _(df, gdf):
    # The CSV and GeoPackage share a common 'geom_id' column.
    # This merge lets you map any CSV column spatially.
    joined = gdf[["geom_id", "geometry"]].merge(df, on="geom_id", how="left")
    joined.head()
    return (joined,)


# ── 5. Choropleth map ────────────────────────────────────────────────────────


@app.cell
def _(df, joined):
    import matplotlib.pyplot as plt

    # Change `col` to any extract column from df.columns
    extract_cols = [c for c in df.columns if c not in ["geom_id", "feature_collection"] and not c.startswith(("boundary.",))]
    col = extract_cols[0] if extract_cols else None

    fig, ax = plt.subplots(figsize=(12, 7))
    joined.plot(column=col, legend=True, cmap="YlOrRd", ax=ax)
    ax.set_title(col or "Features")
    ax.axis("off")
    plt.tight_layout()
    fig
    return ax, col, extract_cols, fig, plt


# ── 6. Time series (mean per extract column) ─────────────────────────────────


@app.cell
def _(df, plt):
    # Mean of each extract column — useful when columns represent time periods.
    extract_cols = [c for c in df.columns if c not in ["geom_id", "feature_collection"] and not c.startswith(("boundary.",))]

    extract_numeric = df.drop(columns=[c for c in df.columns if c not in extract_cols], errors="ignore").select_dtypes("number")
    means = extract_numeric.mean()

    fig2, ax2 = plt.subplots(figsize=(12, 4))
    means.plot(ax=ax2, marker="o")
    ax2.set_title("Mean value per extract column")
    ax2.set_ylabel("Mean")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    fig2
    return ax2, fig2, means


if __name__ == "__main__":
    app.run()
