"""
tests/test_watchlist.py — CineLog

Tests for the watchlist service. Fixtures and assertion style follow
tests/test_collection.py so both suites read the same way.
"""

import pytest
from app import create_app, db
from models import User, Film, WatchlistEntry
from services.collection_service import FilmNotFoundError
from services.watchlist_service import (
    get_watchlist,
    add_to_watchlist,
    AlreadyInWatchlistError,
)


@pytest.fixture
def app():
    """Create an isolated test app with an in-memory database."""
    app = create_app(config={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_user(app):
    """A user to use in tests."""
    with app.app_context():
        user = User(username="testuser", email="test@example.com")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def sample_film(app):
    """A film to use in tests."""
    with app.app_context():
        film = Film(title="Paddington 2", year=2017, genre="Comedy")
        db.session.add(film)
        db.session.commit()
        return film.id


# ── Nonexistent film ─────────────────────────────────────────────────────────

def test_add_to_watchlist_nonexistent_film_raises(app, sample_user):
    """
    Adding a film_id that doesn't exist in the database should raise
    FilmNotFoundError, not a database integrity error.
    """
    with app.app_context():
        nonexistent_film_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(FilmNotFoundError):
            add_to_watchlist(user_id=sample_user, film_id=nonexistent_film_id)


# ── Deduplication ────────────────────────────────────────────────────────────

def test_add_to_watchlist_duplicate_raises(app, sample_user, sample_film):
    """
    Adding the same film twice should raise AlreadyInWatchlistError,
    not silently create a duplicate entry.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        with pytest.raises(AlreadyInWatchlistError):
            add_to_watchlist(user_id=sample_user, film_id=sample_film)

        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 1


# ── get_watchlist sort order ─────────────────────────────────────────────────

def test_get_watchlist_returns_newest_first(app, sample_user):
    """
    get_watchlist() should return films sorted by date_added descending
    (most recently added first), matching get_collection's ordering.
    """
    with app.app_context():
        from datetime import datetime, timezone, timedelta

        # Titles are deliberately in the opposite order to date_added, so an
        # alphabetical sort and a date_added sort cannot both pass.
        film_a = Film(title="Alien", year=1979, genre="Horror")
        film_b = Film(title="Blade Runner", year=1982, genre="Sci-Fi")
        db.session.add_all([film_a, film_b])
        db.session.commit()

        earlier = datetime.now(timezone.utc) - timedelta(days=5)
        later = datetime.now(timezone.utc)

        entry_a = WatchlistEntry(user_id=sample_user, film_id=film_a.id, date_added=earlier)
        entry_b = WatchlistEntry(user_id=sample_user, film_id=film_b.id, date_added=later)
        db.session.add_all([entry_a, entry_b])
        db.session.commit()

        watchlist = get_watchlist(sample_user)
        titles = [f["title"] for f in watchlist]

        # Blade Runner was added later, so it should come first.
        assert titles[0] == "Blade Runner"
        assert titles[1] == "Alien"


# ── Default visibility ───────────────────────────────────────────────────────

def test_add_to_watchlist_defaults_to_private(app, sample_user, sample_film):
    """
    A watchlist entry created without an explicit visibility should be
    private. See pr-response.md (Comment 4) for the reasoning behind this
    default.
    """
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert entry.public is False


def test_add_to_watchlist_respects_explicit_public(app, sample_user, sample_film):
    """
    Callers can opt a watchlist entry into public visibility explicitly,
    rather than depending on whatever the default happens to be.
    """
    with app.app_context():
        entry = add_to_watchlist(
            user_id=sample_user, film_id=sample_film, public=True
        )

        assert entry.public is True
