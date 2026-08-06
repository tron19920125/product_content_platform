from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from product_content_platform.domain import DomainValidationError, ProductProfile


class SkuImportParser:
    """Parses the platform's fixed CSV/XLSX SKU import shape."""

    _aliases = {
        "sku": ("sku", "商品编码"),
        "name": ("商品名称", "name", "product_name"),
        "category": ("品类", "category"),
        "model": ("型号", "model"),
        "selling_points": ("卖点", "selling_points"),
        "parameters": ("参数", "parameters"),
        "brand_requirements": ("品牌要求", "brand_requirements"),
        "output_requirements": ("输出要求", "output_requirements"),
    }

    def parse(self, file_name: str, content: bytes, default_category: str = "") -> list[ProductProfile]:
        suffix = Path(file_name).suffix.lower()
        if not content:
            raise DomainValidationError("导入文件不能为空")
        if suffix == ".csv":
            rows = self._read_csv(content)
        elif suffix == ".xlsx":
            rows = self._read_xlsx(content)
        else:
            raise DomainValidationError("仅支持 CSV 或 XLSX 导入")
        return self._to_profiles(rows, default_category.strip())

    def _read_csv(self, content: bytes) -> list[dict[str, str]]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content.decode("gb18030")
            except UnicodeDecodeError as exc:
                raise DomainValidationError("CSV 编码应为 UTF-8 或 GB18030") from exc
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]

    def _read_xlsx(self, content: bytes) -> list[dict[str, str]]:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as workbook:
                shared = self._shared_strings(workbook)
                sheet_name = next(
                    (name for name in workbook.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")),
                    None,
                )
                if sheet_name is None:
                    raise DomainValidationError("XLSX 中没有可读取的工作表")
                root = ElementTree.fromstring(workbook.read(sheet_name))
        except (zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
            raise DomainValidationError("XLSX 文件格式无效") from exc

        matrix: list[list[str]] = []
        for row in root.iter():
            if not row.tag.endswith("}row"):
                continue
            values: dict[int, str] = {}
            for cell in row:
                if not cell.tag.endswith("}c"):
                    continue
                reference = cell.attrib.get("r", "A1")
                letters = re.match(r"[A-Z]+", reference)
                column = self._column_index(letters.group(0) if letters else "A")
                value = ""
                value_node = next((node for node in cell if node.tag.endswith("}v")), None)
                inline_node = next((node for node in cell.iter() if node.tag.endswith("}t")), None)
                if cell.attrib.get("t") == "s" and value_node is not None and value_node.text:
                    index = int(value_node.text)
                    value = shared[index] if index < len(shared) else ""
                elif inline_node is not None and inline_node.text:
                    value = inline_node.text
                elif value_node is not None and value_node.text:
                    value = value_node.text
                values[column] = value.strip()
            if values:
                width = max(values) + 1
                matrix.append([values.get(index, "") for index in range(width)])

        if not matrix:
            return []
        headers = [value.strip() for value in matrix[0]]
        return [
            {header: row[index].strip() if index < len(row) else "" for index, header in enumerate(headers) if header}
            for row in matrix[1:]
        ]

    @staticmethod
    def _shared_strings(workbook: zipfile.ZipFile) -> list[str]:
        if "xl/sharedStrings.xml" not in workbook.namelist():
            return []
        root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
        return ["".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")) for item in root]

    @staticmethod
    def _column_index(letters: str) -> int:
        value = 0
        for letter in letters:
            value = value * 26 + ord(letter) - ord("A") + 1
        return value - 1

    def _to_profiles(self, rows: list[dict[str, str]], default_category: str) -> list[ProductProfile]:
        profiles: list[ProductProfile] = []
        for row_number, row in enumerate(rows, start=2):
            normalized = {str(key).strip().lower(): str(value or "").strip() for key, value in row.items()}
            if not any(normalized.values()):
                continue
            value = lambda field: next((normalized.get(alias.lower(), "") for alias in self._aliases[field] if normalized.get(alias.lower(), "")), "")
            sku = value("sku")
            name = value("name")
            category = value("category") or default_category
            if not sku or not name or not category:
                raise DomainValidationError(f"第 {row_number} 行缺少 SKU、商品名称或品类")
            profiles.append(
                ProductProfile(
                    sku=sku,
                    name=name,
                    category=category,
                    model=value("model"),
                    selling_points=tuple(self._split_values(value("selling_points"))),
                    parameters=self._parse_parameters(value("parameters"), row_number),
                    brand_requirements=value("brand_requirements"),
                    output_requirements=value("output_requirements"),
                )
            )
        if not profiles:
            raise DomainValidationError("导入文件中没有有效 SKU")
        if len(profiles) > 500:
            raise DomainValidationError("单次最多导入 500 个 SKU")
        return profiles

    @staticmethod
    def _split_values(value: str) -> list[str]:
        return [part.strip() for part in re.split(r"[|;；\n]", value) if part.strip()]

    @classmethod
    def _parse_parameters(cls, value: str, row_number: int) -> dict[str, str]:
        parameters: dict[str, str] = {}
        for part in cls._split_values(value):
            separator = "=" if "=" in part else ":" if ":" in part else "：" if "：" in part else ""
            if not separator:
                raise DomainValidationError(f"第 {row_number} 行参数格式应为 名称=值")
            key, item_value = (segment.strip() for segment in part.split(separator, 1))
            if key and item_value:
                parameters[key] = item_value
        return parameters
