"""One source-bound cold-media entrance for an explicitly built generation."""


def pin(messages, region_end, *, cwd, session, source_layout):
    if cwd is None:
        return None
    from memory.wsc_media_archive import create
    catalog = create(messages, region_end, cwd=cwd, session=session,
                     source_layout=source_layout)
    if catalog is None:
        return None
    from pathlib import Path
    from synaptic.types import Pin
    path = Path(catalog['path']).as_posix()
    owned = sum(record['availability'] == 'owned_exact_asset' for record in catalog['records'])
    sources = sorted({record['source_index'] for record in catalog['records']})
    source_text = ','.join(f'#{index}' for index in sources[:8])
    return Pin(key='media_archive', label='已归档媒体',
               text=f"owned_images={owned} reference_only={catalog['count']-owned} "
                    f"source_indices={source_text} source_count={len(sources)} "
                    f"Read(file_path={path!r}, offset=1, limit={min(8, catalog['count'])}) records={catalog['count']}")
