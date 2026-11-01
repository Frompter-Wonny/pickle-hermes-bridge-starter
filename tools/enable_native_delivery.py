"""Explicit local opt-in for RAM-only native clipboard/context-menu delivery."""
import argparse,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def enable(root,consent=False):
    if consent is not True:raise ValueError('Explicit owner consent is required')
    state=Path(root)/'.runtime'
    if not state.is_dir():raise ValueError('Initialize private local state first')
    path=state/'delivery_preferences.json'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump({'input_method':'context_paste','mode':'background_only','native_clipboard_consent':True,
                   'source':'Local owner explicitly ran enable_native_delivery.py --consent.',
                   'concurrent_user_typing_manually_verified':False},f)
    return path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--consent',action='store_true',help='Owner explicitly permits temporary clipboard use, RAM-only format preservation, and background context-menu Paste.')
    args=parser.parse_args()
    if not args.consent:parser.error('Read SETUP and SECURITY first; opt in explicitly with --consent.')
    path=enable(ROOT,args.consent)
    print('Enabled native background delivery in private settings. No clipboard or UI action was performed.')

if __name__=='__main__':main()
