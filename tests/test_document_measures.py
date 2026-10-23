from tools import document_measures

TMDL = """table _Measures
\tlineageTag: 1

\t/// Daily VaR in euros.
\tmeasure 'VaR 99%' =
\t\t\tIF ( HASONEVALUE ( dim_method[method_id] ),
\t\t\t    SUM ( fact_var[var_99_eur] ) )
\t\tformatString: #,##0
\t\tdisplayFolder: Risk
\t\tlineageTag: 2

\t/// A text measure.
\tmeasure 'Traffic Light' =
\t\t\t"Green"
\t\tdisplayFolder: Risk
\t\tlineageTag: 3

\tcolumn Value
\t\tisHidden
"""


def test_measures_are_read_with_their_description_format_folder_and_dax():
    measures = document_measures.parse_measures(TMDL)
    assert [measure.name for measure in measures] == ["VaR 99%", "Traffic Light"]
    var = measures[0]
    assert var.description == "Daily VaR in euros." and var.format_string == "#,##0" and var.folder == "Risk"
    assert var.dax == "IF ( HASONEVALUE ( dim_method[method_id] ),\n    SUM ( fact_var[var_99_eur] ) )"
    assert measures[1].format_string == "" and measures[1].dax == '"Green"'


def test_markdown_groups_the_measures_by_folder():
    text = document_measures.to_markdown(document_measures.parse_measures(TMDL))
    assert "## Risk" in text and "### VaR 99%" in text and "Format: `#,##0`" in text
    assert text.count("```dax") == 2
