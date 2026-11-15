package com.qahelper;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

class ApiError extends RuntimeException {
  final int status;

  ApiError(int status, String message) {
    super(message);
    this.status = status;
  }

  static ApiError bad(String message) {
    return new ApiError(400, message);
  }

  static ApiError missing() {
    return new ApiError(404, "Not found.");
  }
}

@RestControllerAdvice
class Errors {
  @ExceptionHandler(ApiError.class)
  ResponseEntity<Map<String, String>> api(ApiError e) {
    return ResponseEntity.status(e.status).body(Map.of("error", e.getMessage()));
  }

  @ExceptionHandler({HttpMessageNotReadableException.class, MaxUploadSizeExceededException.class})
  ResponseEntity<Map<String, String>> invalid(Exception e) {
    return ResponseEntity.badRequest()
        .body(Map.of("error", "Invalid request body or upload exceeds 50 MB."));
  }
}
