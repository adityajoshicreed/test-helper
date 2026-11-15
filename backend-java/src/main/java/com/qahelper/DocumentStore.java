package com.qahelper;

import static com.qahelper.Json.*;

import java.sql.Statement;
import java.util.*;
import java.util.function.Consumer;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

/**
 * Stores version-independent API documents in H2. All read/modify/write operations are serialized.
 */
@Repository
public class DocumentStore {
  private final JdbcTemplate jdbc;

  DocumentStore(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  synchronized Map<String, Object> create(String kind, Long parent, Map<String, Object> fields) {
    var doc = copy(fields);
    doc.putIfAbsent("created_at", now());
    var key = new GeneratedKeyHolder();
    jdbc.update(
        c -> {
          var ps =
              c.prepareStatement(
                  "INSERT INTO documents(kind,parent_id,payload) VALUES (?,?,?)",
                  Statement.RETURN_GENERATED_KEYS);
          ps.setString(1, kind);
          ps.setObject(2, parent);
          ps.setString(3, write(doc));
          return ps;
        },
        key);
    long id = Objects.requireNonNull(key.getKey()).longValue();
    doc.put("id", id);
    save(kind, id, doc);
    return copy(doc);
  }

  synchronized Map<String, Object> get(String kind, long id) {
    var values =
        jdbc.query(
            "SELECT payload FROM documents WHERE kind=? AND id=?",
            (rs, n) -> map(read(rs.getString(1))),
            kind,
            id);
    if (values.isEmpty()) throw ApiError.missing();
    return values.getFirst();
  }

  synchronized List<Map<String, Object>> list(String kind) {
    return jdbc.query(
        "SELECT payload FROM documents WHERE kind=? ORDER BY id DESC",
        (rs, n) -> map(read(rs.getString(1))),
        kind);
  }

  synchronized List<Map<String, Object>> children(String kind, long parent) {
    return jdbc.query(
        "SELECT payload FROM documents WHERE kind=? AND parent_id=? ORDER BY id",
        (rs, n) -> map(read(rs.getString(1))),
        kind,
        parent);
  }

  synchronized Map<String, Object> update(
      String kind, long id, Consumer<Map<String, Object>> change) {
    var doc = get(kind, id);
    change.accept(doc);
    save(kind, id, doc);
    return copy(doc);
  }

  private void save(String kind, long id, Map<String, Object> doc) {
    jdbc.update("UPDATE documents SET payload=? WHERE kind=? AND id=?", write(doc), kind, id);
  }
}
