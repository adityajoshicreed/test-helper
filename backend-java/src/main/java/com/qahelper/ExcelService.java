package com.qahelper;

import static com.qahelper.Json.*;

import java.nio.file.*;
import java.util.*;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.ss.util.CellRangeAddress;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.stereotype.Service;

@Service
class ExcelService {
  static final List<String> META =
      List.of(
          "environment",
          "pre_requisite",
          "created_by",
          "sprint",
          "lob",
          "vertical",
          "feasible_for_automation",
          "test_case_applicability",
          "labels",
          "test_case_status");
  static final String[] COLUMNS = {
    "S.No",
    "Test Case Name",
    "Test Case Description",
    "Environment",
    "Pre-Requisite",
    "Step #",
    "Step Description",
    "Test Data",
    "Expected Result",
    "Actual Result",
    "Created By",
    "Sprint",
    "LOB",
    "Vertical",
    "Feasible for Automation?",
    "Test Case Applicability",
    "Labels",
    "Status"
  };

  String path(Map<String, Object> b) {
    String value = required(b, "excel_path");
    Path p = Path.of(value);
    if (!p.isAbsolute() || !value.toLowerCase(Locale.ROOT).matches(".*\\.(xlsx|xlsm)$"))
      throw ApiError.bad("Excel file location must be an absolute .xlsx path.");
    return p.normalize().toString();
  }

  static String result(Object code, Object body) {
    return "Response Code: "
        + (code == null ? "N/A" : code)
        + "\nResponse Body:\n"
        + (body == null || text(body).isEmpty() ? "(no response body)" : body);
  }

  int write(List<Map<String, Object>> cases, String destination) {
    Path target = Path.of(destination), temporary = null;
    int count = 0;
    try (var workbook = new XSSFWorkbook()) {
      var sheet = workbook.createSheet("Test Cases");
      var bold = workbook.createFont();
      bold.setBold(true);
      var header = workbook.createCellStyle();
      header.setFont(bold);
      var wrap = workbook.createCellStyle();
      wrap.setWrapText(true);
      wrap.setVerticalAlignment(VerticalAlignment.TOP);
      var title = sheet.createRow(0);
      for (int i = 0; i < COLUMNS.length; i++) {
        title.createCell(i).setCellValue(COLUMNS[i]);
        title.getCell(i).setCellStyle(header);
        sheet.setColumnWidth(i, (i >= 6 && i <= 9 ? 45 : 20) * 256);
      }
      int row = 1, caseNumber = 0;
      for (var c : cases) {
        int begin = row;
        caseNumber++;
        var steps = rows(c.get("steps"));
        count += steps.size();
        if (steps.isEmpty()) steps = List.of(obj());
        int stepNumber = 0;
        for (var step : steps) {
          Object[] values = {
            caseNumber,
            c.get("name"),
            c.get("description"),
            c.get("environment"),
            c.get("pre_requisite"),
            ++stepNumber,
            step.get("description"),
            step.get("test_data"),
            step.get("expected_result"),
            step.get("actual_result"),
            c.get("created_by"),
            c.get("sprint"),
            c.get("lob"),
            c.get("vertical"),
            c.get("feasible_for_automation"),
            c.get("test_case_applicability"),
            c.get("labels"),
            c.get("test_case_status")
          };
          var r = sheet.createRow(row++);
          for (int i = 0; i < values.length; i++) {
            var cell = r.createCell(i);
            String value = text(values[i]);
            if (value.length() > 32767) value = value.substring(0, 32767);
            if (values[i] instanceof Number n) cell.setCellValue(n.doubleValue());
            else cell.setCellValue(value);
            cell.setCellStyle(wrap);
          }
        }
        if (row - begin > 1)
          for (int col : new int[] {0, 1, 2, 3, 4, 10, 11, 12, 13, 14, 15, 16, 17})
            sheet.addMergedRegion(new CellRangeAddress(begin, row - 1, col, col));
      }
      Files.createDirectories(target.getParent());
      temporary = Files.createTempFile(target.getParent(), "qa-export-", ".xlsx");
      try (var output = Files.newOutputStream(temporary)) {
        workbook.write(output);
      }
      Files.move(temporary, target, StandardCopyOption.REPLACE_EXISTING);
      return count;
    } catch (Exception e) {
      throw ApiError.bad("Could not write Excel file: " + e.getMessage());
    } finally {
      if (temporary != null)
        try {
          Files.deleteIfExists(temporary);
        } catch (Exception ignored) {
        }
    }
  }
}
