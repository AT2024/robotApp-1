# Failure Analysis Template

## Test Information
- **Scenario**: {{scenario_name}}
- **Failed Step**: {{step_id}}
- **Timestamp**: {{timestamp}}

## Failure Details

### What Happened
{{failure_description}}

### Expected Result
{{expected}}

### Actual Result
{{actual}}

## Diagnostic Information

### Console Errors
```
{{console_errors}}
```

### Network Requests
```
{{network_requests}}
```

### Element State
- **Target**: {{target_element}}
- **Found**: {{element_found}}
- **Ref ID**: {{ref_id}}
- **Coordinates**: {{coordinates}}

## Recovery Attempts

### Alternative Selectors Tried
{{alternatives_tried}}

### Results
{{recovery_results}}

## Suggested Fix

### Root Cause Analysis
{{root_cause}}

### Recommended Changes
{{recommended_changes}}

### Code Changes
```{{language}}
{{code_changes}}
```

## Next Steps
1. {{next_step_1}}
2. {{next_step_2}}
3. {{next_step_3}}
