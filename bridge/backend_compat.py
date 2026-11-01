"""Process-local snapshot adapter; never patches installed Hermes source files."""
import re
from .store import Denied


def clear_snapshot(backend):
    backend._snapshot_id=None
    backend._snapshot_tokens={}
    backend._bridge_snapshot_indices=None


def remember_snapshot(backend,raw,target,allow_truncated=False):
    """Bind elements and tokens to the one response which supplied them."""
    clear_snapshot(backend)
    if not isinstance(raw,dict):raise Denied('bridge_snapshot_read_failed')
    data=raw.get('structuredContent') or {}
    if raw.get('isError') or not isinstance(data,dict):raise Denied('bridge_snapshot_read_failed')
    if (data.get('pid'),data.get('window_id'))!=tuple(target):raise Denied('bridge_snapshot_target_mismatch')
    if data.get('truncated') and not allow_truncated:raise Denied('bridge_snapshot_truncated')
    snapshot=data.get('snapshot_id');rows=data.get('elements')
    if not isinstance(snapshot,str) or not re.fullmatch(r's[0-9a-f]{8}',snapshot):raise Denied('bridge_snapshot_id_required')
    if not isinstance(rows,list) or not rows:raise Denied('bridge_structured_elements_required')
    indices=set();tokens={}
    for row in rows:
        if not isinstance(row,dict):raise Denied('bridge_snapshot_element_invalid')
        idx=row.get('element_index')
        if type(idx) is not int or idx<0 or idx in indices:raise Denied('bridge_snapshot_element_index_invalid')
        indices.add(idx);token=row.get('element_token')
        if token is not None:
            if not isinstance(token,str) or not token:raise Denied('bridge_snapshot_token_invalid')
            tokens[idx]=token
    backend._snapshot_id=snapshot;backend._snapshot_tokens=tokens;backend._bridge_snapshot_indices=indices
    return rows


def adapt_backend(backend):
    """Keep original capture/render/action methods; retain their exact raw snapshot.

    Request structured elements so model labels and action tokens come from the
    same response. No extra capture is inserted after rendering, and no global
    Hermes method, approval callback, permission mode or input policy is changed.
    """
    if getattr(backend,'_bridge_snapshot_adapter',False):return backend
    names=['_gws_args','_fetch_or_refetch','_set_active_target','_clear_active_target']
    if any(not callable(getattr(backend,n,None)) for n in names):raise Denied('bridge_backend_snapshot_hooks_not_supported')
    original_args=backend._gws_args;original_fetch=backend._fetch_or_refetch;original_target=backend._set_active_target;original_clear=backend._clear_active_target
    def args():
        if not backend._session.supports_input_property('get_window_state','tree_format'):
            clear_snapshot(backend);raise Denied('bridge_structured_capture_not_supported')
        result=dict(original_args());result['tree_format']='elements'
        return result
    def fetch(tool,parameters,*rest,**kwargs):
        if tool=='get_window_state':clear_snapshot(backend)
        raw=original_fetch(tool,parameters,*rest,**kwargs)
        if tool=='get_window_state':
            target=getattr(backend,'_last_target',{}) or {}
            if (parameters.get('pid'),parameters.get('window_id'))!=(target.get('pid'),target.get('window_id')):
                raise Denied('bridge_snapshot_request_target_changed')
            remember_snapshot(backend,raw,(target.get('pid'),target.get('window_id')))
        return raw
    def set_target(*a,**kw):
        clear_snapshot(backend)
        return original_target(*a,**kw)
    def clear_target(*a,**kw):
        clear_snapshot(backend)
        return original_clear(*a,**kw)
    clear_snapshot(backend)
    backend._clear_active_target=clear_target
    backend._gws_args=args;backend._fetch_or_refetch=fetch;backend._set_active_target=set_target
    backend._bridge_snapshot_adapter=True
    return backend
