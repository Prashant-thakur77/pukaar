from __future__ import annotations

from sqlmodel import Session

from Pukaar.db.database import edge_engine, init_db
from Pukaar.models.domain import Site


def _upsert_site(session: Session, payload: dict[str, object]) -> None:
    site_id = str(payload['id'])
    site = session.get(Site, site_id)
    if site is None:
        session.add(Site(**payload))
        return

    for key, value in payload.items():
        setattr(site, key, value)


def seed() -> None:
    init_db()

    sites = [
        {
            'id': 'puente-arroyo-01',
            'name': 'Arroyo Bridge 01',
            'region': 'South Littoral',
            'lat': -32.9468,
            'lng': -60.6393,
            'description': 'Main bridge on provincial route',
            'is_active': True,
        },
        {
            'id': 'calle-baja-02',
            'name': 'Low Street 02',
            'region': 'North Littoral',
            'lat': -32.9568,
            'lng': -60.6493,
            'description': 'Frequently flooded low-water crossing',
            'is_active': True,
        },
    ]

    with Session(edge_engine) as session:
        for site_payload in sites:
            _upsert_site(session, site_payload)
        session.commit()
        print(f'Seed complete. Sites available: {len(sites)}')


if __name__ == '__main__':
    seed()
