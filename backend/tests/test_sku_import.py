from __future__ import annotations

import io
import unittest
import zipfile

from product_content_platform.adapters import SkuImportParser


class SkuImportParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = SkuImportParser()

    def test_csv_supports_fixed_chinese_headers(self) -> None:
        content = "SKU,商品名称,品类,卖点,参数\nX11,COLMO X11,洗衣机,低温柔洗|智能投放,容量=12kg".encode()

        profiles = self.parser.parse("items.csv", content)

        self.assertEqual("X11", profiles[0].sku)
        self.assertEqual(("低温柔洗", "智能投放"), profiles[0].selling_points)
        self.assertEqual({"容量": "12kg"}, profiles[0].parameters)

    def test_xlsx_reads_inline_string_cells(self) -> None:
        cells = [
            ["SKU", "商品名称", "品类", "型号"],
            ["T1", "COLMO T1", "干衣机", "T1"],
        ]
        rows = []
        for row_number, values in enumerate(cells, start=1):
            cell_xml = "".join(
                f'<c r="{chr(65 + index)}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>'
                for index, value in enumerate(values)
            )
            rows.append(f'<row r="{row_number}">{cell_xml}</row>')
        sheet = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(rows)}</sheetData></worksheet>'
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as workbook:
            workbook.writestr("xl/worksheets/sheet1.xml", sheet)

        profiles = self.parser.parse("items.xlsx", output.getvalue())

        self.assertEqual("T1", profiles[0].sku)
        self.assertEqual("干衣机", profiles[0].category)


if __name__ == "__main__":
    unittest.main()
