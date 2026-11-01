"""Read-only Markdown tools constrained to operator-configured source roots."""
import subprocess
import shutil
import os
from pathlib import Path


class Notes:
    def __init__(self,roots):
        if not isinstance(roots,dict) or not roots:raise ValueError('note_sources_required')
        self.roots={name:Path(path).expanduser().resolve(strict=True) for name,path in roots.items()}
        if any(not path.is_dir() for path in self.roots.values()):raise ValueError('source_directory_required')

    def path(self,source,path):
        root=self.roots[source];resolved=(root/path).resolve(strict=True)
        if not resolved.is_relative_to(root) or resolved.suffix.lower()!='.md' or not resolved.is_file():
            raise ValueError('markdown_within_source_required')
        return resolved

    def read(self,source,path,start_line=1,line_count=80):
        if not 1<=start_line or not 1<=line_count<=200:raise ValueError('invalid_line_range')
        file=self.path(source,path)
        if file.stat().st_size>2_000_000:raise ValueError('note_too_large')
        lines=file.read_text().splitlines();chunk=lines[start_line-1:start_line-1+line_count]
        content='\n'.join(chunk)
        return {'path':str(file.relative_to(self.roots[source])),'start_line':start_line,
                'total_lines':len(lines),'text':content[:16000],'truncated':len(content)>16000}

    def search(self,source,query,mode='filename',offset=0,max_results=30):
        if not isinstance(query,str) or not query.strip() or len(query)>200:raise ValueError('invalid_query')
        if not 0<=offset or not 1<=max_results<=200:raise ValueError('invalid_result_range')
        root=self.roots[source]
        rg=shutil.which('rg')
        if not rg:
            # launchd does not inherit Codex's bundled rg. Keep the same source
            # boundary using standard-library I/O; never retry an OS access denial.
            if mode not in {'filename','content'}:raise ValueError('invalid_search_mode')
            matches=[]
            for directory,dirs,names in os.walk(root,followlinks=False):
                dirs[:]=[name for name in dirs if not name.startswith('.')]
                for name in names:
                    if name.startswith('.') or not name.endswith('.md'):continue
                    file=(Path(directory)/name).resolve()
                    if not file.is_relative_to(root):continue
                    relative=str(file.relative_to(root))
                    if mode=='filename':found=query.casefold() in relative.casefold()
                    else:
                        try:
                            if file.stat().st_size>2_000_000:continue
                            found=query.casefold() in file.read_text(errors='replace').casefold()
                        except OSError:continue
                    if found:matches.append(relative)
            matches.sort()
            return {'paths':matches[offset:offset+max_results],'total_matches':len(matches),
                    'next_offset':offset+max_results if len(matches)>offset+max_results else None}
        if mode=='filename':
            command=[rg,'--files','-g','*.md',str(root)]
        elif mode=='content':
            command=[rg,'-l','-i','-F','--max-filesize','2M','-g','*.md','--',query,str(root)]
        else:raise ValueError('invalid_search_mode')
        try:result=subprocess.run(command,capture_output=True,text=True,timeout=20)
        except subprocess.TimeoutExpired:raise ValueError('note_search_timeout') from None
        if result.returncode not in {0,1}:raise ValueError('note_search_failed')
        matches=[]
        for name in result.stdout.splitlines():
            path=Path(name).resolve()
            if not path.is_relative_to(root):continue
            relative=str(path.relative_to(root))
            if mode=='filename' and query.casefold() not in relative.casefold():continue
            matches.append(relative)
        matches.sort()
        return {'paths':matches[offset:offset+max_results],'total_matches':len(matches),
                'next_offset':offset+max_results if len(matches)>offset+max_results else None}
