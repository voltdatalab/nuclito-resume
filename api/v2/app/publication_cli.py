"""Manual, opt-in schema and worker commands. Importing this module performs no I/O."""
import argparse
import asyncio
import os
import time


async def generate(item):
    # No OpenAI import/client until a claimed, eligible job actually needs it.
    from app.publication_generation import generate as production_generate
    return await production_generate(item)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Publication inbox operations (explicit opt-in)')
    commands = parser.add_subparsers(dest='command', required=True)
    schema = commands.add_parser('schema')
    schema.add_argument('--apply', action='store_true')
    worker = commands.add_parser('worker')
    worker.add_argument('--run', action='store_true')
    worker.add_argument('--once', action='store_true')
    reconcile_parser = commands.add_parser('reconcile')
    reconcile_parser.add_argument('--apply', action='store_true')
    reconcile_parser.add_argument('--pages', type=int, default=1)
    reconcile_parser.add_argument('--known', type=int, default=20)
    reconcile_parser.add_argument('--page-size', type=int, default=20)
    args = parser.parse_args(argv)
    if args.command == 'reconcile':
        if not args.apply:
            print('No changes. Reconciliation requires --apply and PUBLICATION_SYNC_ENABLED=1.')
            return 0
        if (os.getenv('PUBLICATION_SYNC_ENABLED') != '1' or not 1 <= args.pages <= 10
                or not 1 <= args.known <= 100 or not 1 <= args.page_size <= 100):
            parser.error('reconcile requires opt-in and bounded pages/known/page-size')
    if args.command == 'schema' and not args.apply:
        print('No changes. Provisioning requires schema --apply.')
        return 0
    if args.command == 'worker' and (not args.run or os.getenv('PUBLICATION_SYNC_ENABLED') != '1'):
        parser.error('worker requires --run and PUBLICATION_SYNC_ENABLED=1')
    engine = None
    try:
        # Deliberately after all opt-in checks; reuses the existing engine config.
        from app.model import engine
        from app.publication_sync import Inbox, provision, work_once
        if args.command == 'schema':
            provision(engine)
            print('Publication inbox and reconciliation cursor provisioned.')
        elif args.command == 'reconcile':
            from app.models.posts import Post
            from app.publication_reconcile import reconcile
            from app.publication_source import GhostAdmin
            source = GhostAdmin(os.getenv('PUBLICATION_GHOST_ADMIN_ORIGIN', ''),
                                os.getenv('PUBLICATION_GHOST_ADMIN_KEY', ''))
            counts = reconcile(Inbox(engine, Post.__table__), source, pages=args.pages,
                               known=args.known, page_size=args.page_size)
            print('Reconciled pages={pages} checked={checked}.'.format(**counts))
        else:
            from app.models.posts import Post
            inbox = Inbox(engine, Post.__table__)
            while True:
                processed = asyncio.run(work_once(inbox, generate))
                if args.once:
                    break
                if not processed:
                    time.sleep(1)
        return 0
    except Exception:
        print('Publication operation failed; no diagnostic payload emitted.')
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
