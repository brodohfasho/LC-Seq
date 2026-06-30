# Agent Instructions for LC-Seq Development

This document provides core principles and guidelines for AI agents working on the LC-Seq chromatographic data analysis application.

## Core Principles

### 1. Code Quality and Architecture
- **Build with care and scalability in mind**: Always consider how the code will scale as the application grows
- **Follow best practices**: Adhere to SOLID principles, Google Style Guide, modern programming patterns, and clean code rules
- **Maintain high code quality**: Ensure proper code structure, documentation, and maintainability
- **Include proper documentation**: All modules should have docstrings, and file headers should include relative paths
- **Avoid generic fallbacks**: Never use fallback methods that return generic results unless explicitly requested

### 2. User Communication
- **Ask before proceeding**: When in doubt or when requirements are unclear, ask the user questions before taking action
- **Clarify specifications**: Ensure the program is built exactly to the user's specifications by seeking clarification when needed
- **Provide context**: Explain decisions and trade-offs when making architectural choices

### 3. Procedural Development
- **Consult ROADMAP.md first**: Before taking any action, consult the ROADMAP.md file to ensure:
  - The app is built procedurally and in the correct order
  - Only user requirements are constructed (avoid scope creep)
  - Development follows the planned sequence
- **Update roadmap**: If the roadmap needs adjustment, discuss with the user before making changes

### 4. Version Control
- **Frequent commits**: Commit and push to GitHub frequently after accomplishing tasks
- **Meaningful commit messages**: Write clear, descriptive commit messages that explain what was done
- **Provide summaries**: After commits, provide a summary of:
  - What was accomplished
  - Why it was implemented in that way
  - Any important decisions or considerations

### 5. Testing and Validation
- **Run tests frequently**: Regularly run tests to ensure things are being built properly
- **Validate functionality**: Test features as they are implemented to catch issues early
- **Maintain test coverage**: Ensure adequate test coverage for critical functionality

## Development Workflow

1. **Before starting any task**:
   - Read and understand ROADMAP.md
   - Check current project state
   - Clarify any ambiguities with the user

2. **During development**:
   - Follow coding standards and best practices
   - Write clean, maintainable code
   - Add appropriate documentation
   - Test as you go

3. **After completing tasks**:
   - Run tests to verify functionality
   - Commit and push changes with meaningful messages
   - Provide a summary of accomplishments

4. **When encountering issues**:
   - Ask the user for clarification
   - Consult ROADMAP.md for context
   - Propose solutions before implementing

## File Structure Standards

- Include file path comments at the top of every script: `# relative/path/to/file`
- All modules must have docstrings
- Follow consistent naming conventions
- Organize code logically and maintain separation of concerns

## Notes

- The user is a novice programmer and will rely heavily on the agent for development
- The application is for analyzing chromatographic data
- Prioritize clarity and maintainability over clever solutions
- When in doubt, choose the more explicit and understandable approach
