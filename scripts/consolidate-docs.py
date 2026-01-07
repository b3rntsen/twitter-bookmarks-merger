#!/usr/bin/env python3
"""
Documentation Consolidation Utility

Consolidates all project documentation files into a single Documentation-consolidated.md file.
Each source file becomes a main section, and heading levels are normalized.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class Heading:
    """Represents a markdown heading found in a source file."""
    level: int  # 1-6, where 1 = #, 2 = ##, etc.
    text: str  # Heading text (content after # symbols)
    line_number: int  # Line number in source file (0-indexed)
    anchor: str = ""  # Generated anchor for TOC links (lowercase, hyphenated)


@dataclass
class SourceFile:
    """Represents a source documentation file to be processed."""
    path: Path  # File system path to the source file
    name: str  # Filename (e.g., "README.md", "QUICK_START.md")
    content: str = ""  # Raw file content (read from disk)
    headings: List[Heading] = None  # Extracted headings from the file
    min_heading_level: Optional[int] = None  # Minimum heading level found in file (1-6)
    normalized_content: str = ""  # Content after heading normalization
    
    def __post_init__(self):
        """Initialize headings list if not provided."""
        if self.headings is None:
            self.headings = []


def read_file_content(file_path: Path) -> str:
    """
    Read file content with UTF-8 encoding and error handling.
    
    Args:
        file_path: Path to the file to read
        
    Returns:
        File content as string
        
    Raises:
        IOError: If file cannot be read
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except IOError as e:
        raise IOError(f"Failed to read file {file_path}: {e}")


def detect_headings(content: str) -> List[Heading]:
    """
    Detect all markdown headings in content using regex pattern.
    
    Args:
        content: File content to scan for headings
        
    Returns:
        List of Heading objects found in the content
    """
    headings = []
    pattern = re.compile(r'^(#+)\s+(.+)$')
    
    for line_num, line in enumerate(content.split('\n')):
        match = pattern.match(line)
        if match:
            level = len(match.group(1))  # Number of # symbols
            text = match.group(2).strip()
            if text:  # Only add non-empty headings
                headings.append(Heading(
                    level=level,
                    text=text,
                    line_number=line_num
                ))
    
    return headings


def find_min_heading_level(headings: List[Heading]) -> Optional[int]:
    """
    Find the minimum heading level from a list of headings.
    
    Args:
        headings: List of Heading objects
        
    Returns:
        Minimum heading level (1-6) or None if no headings found
    """
    if not headings:
        return None
    
    return min(heading.level for heading in headings)


def calculate_offset(min_level: int) -> int:
    """
    Calculate the offset needed to normalize headings so minimum becomes level 2.
    
    Args:
        min_level: Minimum heading level found in file
        
    Returns:
        Offset to apply (min_level - 2)
    """
    return min_level - 2


def discover_source_files(source_dir: Path) -> List[Path]:
    """
    Discover all documentation files to be consolidated.
    
    Finds Documentation.md, README.md, all files in docs-archive/, and terraform/README.md
    in the correct order: Documentation.md first, then README.md, then docs-archive/*.md
    alphabetically, then terraform/README.md.
    
    Args:
        source_dir: Root directory to search for documentation files
        
    Returns:
        List of file paths in the correct processing order
    """
    files = []
    
    # 1. Documentation.md (main existing doc)
    doc_file = source_dir / "Documentation.md"
    if doc_file.exists():
        files.append(doc_file)
    
    # 2. README.md (project overview)
    readme_file = source_dir / "README.md"
    if readme_file.exists():
        files.append(readme_file)
    
    # 3. docs-archive/*.md (alphabetically sorted)
    docs_archive_dir = source_dir / "docs-archive"
    if docs_archive_dir.exists() and docs_archive_dir.is_dir():
        archive_files = sorted(docs_archive_dir.glob("*.md"))
        files.extend(archive_files)
    
    # 4. terraform/README.md (last, as it's in subdirectory)
    terraform_readme = source_dir / "terraform" / "README.md"
    if terraform_readme.exists():
        files.append(terraform_readme)
    
    return files


def filter_empty_files(file_paths: List[Path]) -> List[Path]:
    """
    Filter out empty files and files containing only whitespace.
    
    Args:
        file_paths: List of file paths to check
        
    Returns:
        List of non-empty file paths
    """
    non_empty_files = []
    
    for file_path in file_paths:
        try:
            content = read_file_content(file_path)
            # Check if file has non-whitespace content
            if content.strip():
                non_empty_files.append(file_path)
        except IOError:
            # Skip files that can't be read
            continue
    
    return non_empty_files


def normalize_headings(content: str, headings: List[Heading], min_level: int) -> str:
    """
    Normalize heading levels in content using two-pass algorithm.
    
    First pass finds minimum heading level, second pass adjusts all headings by offset
    so minimum becomes level 2, preserving relative hierarchy.
    
    Args:
        content: Original file content
        headings: List of Heading objects found in content
        min_level: Minimum heading level in the file
        
    Returns:
        Content with normalized heading levels
    """
    if not headings or min_level is None:
        return content
    
    offset = calculate_offset(min_level)
    if offset == 0:
        # No normalization needed
        return content
    
    lines = content.split('\n')
    heading_pattern = re.compile(r'^(#+)\s+(.+)$')
    
    # Create a map of line numbers to new heading levels
    heading_map = {}
    for heading in headings:
        new_level = heading.level - offset
        # Ensure level doesn't go below 1
        new_level = max(1, new_level)
        heading_map[heading.line_number] = new_level
    
    # Second pass: adjust headings
    normalized_lines = []
    for line_num, line in enumerate(lines):
        match = heading_pattern.match(line)
        if match and line_num in heading_map:
            new_level = heading_map[line_num]
            heading_text = match.group(2)
            normalized_line = '#' * new_level + ' ' + heading_text
            normalized_lines.append(normalized_line)
        else:
            normalized_lines.append(line)
    
    return '\n'.join(normalized_lines)


def create_section(source_file: SourceFile) -> str:
    """
    Convert source file to a main section with level 1 heading from filename.
    
    Args:
        source_file: SourceFile object with normalized content
        
    Returns:
        Markdown section string with main heading and content
    """
    # Generate main heading from filename (remove .md extension)
    main_heading = source_file.name.replace('.md', '')
    
    # Create section with level 1 heading
    section = f"# {main_heading}\n\n"
    
    # Add normalized content
    if source_file.normalized_content:
        section += source_file.normalized_content
    else:
        # If no normalized content, use original content
        section += source_file.content
    
    return section


def assemble_consolidated_document(sections: List[str]) -> str:
    """
    Combine all sections into a single consolidated document.
    
    Args:
        sections: List of section strings (one per source file)
        
    Returns:
        Complete consolidated markdown document
    """
    return '\n\n---\n\n'.join(sections)


def write_consolidated_file(output_path: Path, content: str, dry_run: bool = False) -> None:
    """
    Write consolidated content to output file.
    
    Args:
        output_path: Path to output file
        content: Consolidated markdown content
        dry_run: If True, don't actually write the file
        
    Raises:
        IOError: If file cannot be written
    """
    if dry_run:
        print(f"[DRY RUN] Would write {len(content)} characters to {output_path}")
        return
    
    try:
        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except IOError as e:
        raise IOError(f"Failed to write output file {output_path}: {e}")


def main():
    """Main entry point for the consolidation script."""
    parser = argparse.ArgumentParser(
        description="Consolidate all project documentation files into a single file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/consolidate-docs.py
  python scripts/consolidate-docs.py --output docs/Consolidated.md
  python scripts/consolidate-docs.py --dry-run --verbose
        """
    )
    
    parser.add_argument(
        '--output', '-o',
        default='Documentation-consolidated.md',
        help='Output file path (default: Documentation-consolidated.md)'
    )
    
    parser.add_argument(
        '--source-dir', '-s',
        default='.',
        type=Path,
        help='Root directory to search for docs (default: current directory)'
    )
    
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Show what would be done without writing file'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed processing information'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        print(f"Source directory: {args.source_dir}")
        print(f"Output file: {args.output}")
        print(f"Dry run: {args.dry_run}")
    
    try:
        # Discover source files
        if args.verbose:
            print("Discovering source files...")
        source_files = discover_source_files(args.source_dir)
        
        if not source_files:
            print("Error: No source files found.")
            return 2
        
        # Filter empty files
        source_files = filter_empty_files(source_files)
        
        if not source_files:
            print("Error: No non-empty source files found.")
            return 2
        
        if args.verbose:
            print(f"Found {len(source_files)} source files to process")
        
        # Process each file
        sections = []
        for file_path in source_files:
            if args.verbose:
                print(f"Processing: {file_path}")
            
            # Read file
            content = read_file_content(file_path)
            
            # Detect headings
            headings = detect_headings(content)
            
            # Find minimum heading level
            min_level = find_min_heading_level(headings)
            if min_level is None:
                # File has no headings, use default minimum of 2
                min_level = 2
            
            # Normalize headings
            normalized_content = normalize_headings(content, headings, min_level)
            
            # Create SourceFile object
            source_file = SourceFile(
                path=file_path,
                name=file_path.name,
                content=content,
                headings=headings,
                min_heading_level=min_level,
                normalized_content=normalized_content
            )
            
            # Create section
            section = create_section(source_file)
            sections.append(section)
        
        # Assemble consolidated document
        consolidated_content = assemble_consolidated_document(sections)
        
        # Write output
        output_path = Path(args.output)
        write_consolidated_file(output_path, consolidated_content, args.dry_run)
        
        if not args.dry_run:
            print(f"Successfully created consolidated documentation: {output_path}")
        
        return 0
        
    except IOError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

