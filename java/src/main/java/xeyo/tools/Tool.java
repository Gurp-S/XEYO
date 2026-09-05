import java.util.Map;

public interface Tool {
    String name();
    /** JSON Schema 对象，序列化进 tools/list */
    Map<String, Object> schema();
    ToolResult execute(ToolRequest request) throws Exception;
}