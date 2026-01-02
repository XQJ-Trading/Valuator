# Context Directory

This directory contains contextual knowledge and prompts needed to solve problems. Each file in this directory provides domain-specific guidance and specifications.

## Available Context Files

- **valuation_prompt.md**: Valuation analysis context and specifications
  - Provides execution environment for repeatable analysis
  - Contains modules for industry analysis, leadership evaluation, and segment reclassification
  - Use this when performing valuation tasks

## How to Use

When using the context tool, you can specify which context file to load:

1. **Default**: If no parameters are specified, this README.md is loaded
2. **Profile**: Specify a filename (e.g., `valuation_prompt.md`) to load a specific context file
3. **Path**: Provide an absolute or relative path to any markdown file
4. **Default parameter**: Use `default` parameter to override the default file

## Path Resolution

- Profiles are resolved relative to this directory (`server/core/agent/context/`)
- Absolute paths are used as-is
- Relative paths are resolved from the workspace root

## Usage Example

To load the valuation context:
- Use profile: `valuation_prompt.md`
- Or use path: `server/core/agent/context/valuation_prompt.md`

The context tool will read the file content and generate a plan and action steps based on the loaded context.
