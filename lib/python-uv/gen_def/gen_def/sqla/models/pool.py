
from sqlalchemy import Column, Index, Table, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql.sqltypes import *
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.associationproxy import association_proxy

Base = declarative_base()
metadata = Base.metadata


class Node(Base):
    """
    One row per node_id: its latest public card (latest occurred_at wins).
    """
    __tablename__ = 'Node'

    node_id = Column(Text(), primary_key=True, nullable=False )
    cluster_id = Column(Text(), nullable=False )
    epoch = Column(Text(), nullable=False )
    role = Column(Text(), nullable=False )
    site = Column(Text(), nullable=False )
    location_note = Column(Text())
    endpoints_json = Column(Text())
    wants_json = Column(Text())
    draining = Column(Boolean(), nullable=False )
    announced_at = Column(DateTime(), nullable=False )
    digest = Column(Text(), nullable=False )
    

    def __repr__(self):
        return f"Node(node_id={self.node_id},cluster_id={self.cluster_id},epoch={self.epoch},role={self.role},site={self.site},location_note={self.location_note},endpoints_json={self.endpoints_json},wants_json={self.wants_json},draining={self.draining},announced_at={self.announced_at},digest={self.digest},)"



    


class CollectionPolicy(Base):
    """
    One row per collection: the latest declared policy.
    """
    __tablename__ = 'CollectionPolicy'

    collection = Column(Text(), primary_key=True, nullable=False )
    min_sites = Column(Integer(), nullable=False )
    verify_max_age_days = Column(Integer(), nullable=False )
    evictable = Column(Boolean(), nullable=False )
    declared_at = Column(DateTime(), nullable=False )
    digest = Column(Text(), nullable=False )
    

    def __repr__(self):
        return f"CollectionPolicy(collection={self.collection},min_sites={self.min_sites},verify_max_age_days={self.verify_max_age_days},evictable={self.evictable},declared_at={self.declared_at},digest={self.digest},)"



    


class Blob(Base):
    """
    One row per registered blob — what EXISTS, whoever holds it.
    """
    __tablename__ = 'Blob'

    blob_hash = Column(Text(), primary_key=True, nullable=False )
    byte_size = Column(Integer(), nullable=False )
    collection = Column(Text(), nullable=False )
    first_seen_at = Column(DateTime(), nullable=False )
    digest = Column(Text(), nullable=False )
    chunk_size = Column(Integer())
    chunk_hashes_json = Column(Text())
    chunk_at = Column(DateTime())
    chunk_digest = Column(Text())
    

    def __repr__(self):
        return f"Blob(blob_hash={self.blob_hash},byte_size={self.byte_size},collection={self.collection},first_seen_at={self.first_seen_at},digest={self.digest},chunk_size={self.chunk_size},chunk_hashes_json={self.chunk_hashes_json},chunk_at={self.chunk_at},chunk_digest={self.chunk_digest},)"



    


class BlobLocation(Base):
    """
    One row per (blob, node, epoch): a node's claim to hold a blob in one life of it.
    """
    __tablename__ = 'BlobLocation'

    id = Column(Text(), primary_key=True, nullable=False )
    blob_hash = Column(Text(), nullable=False )
    node_id = Column(Text(), nullable=False )
    epoch = Column(Text(), nullable=False )
    state = Column(Text(), nullable=False )
    pinned = Column(Boolean(), nullable=False )
    stored_at = Column(DateTime())
    last_access_at = Column(DateTime())
    

    def __repr__(self):
        return f"BlobLocation(id={self.id},blob_hash={self.blob_hash},node_id={self.node_id},epoch={self.epoch},state={self.state},pinned={self.pinned},stored_at={self.stored_at},last_access_at={self.last_access_at},)"



    


class ScrubState(Base):
    """
    One row per (node, epoch, collection): where scrub resumes, and the last full pass.
    """
    __tablename__ = 'ScrubState'

    id = Column(Text(), primary_key=True, nullable=False )
    node_id = Column(Text(), nullable=False )
    epoch = Column(Text(), nullable=False )
    collection = Column(Text(), nullable=False )
    cursor = Column(Text())
    pass_started_at = Column(DateTime())
    last_full_pass_at = Column(DateTime())
    

    def __repr__(self):
        return f"ScrubState(id={self.id},node_id={self.node_id},epoch={self.epoch},collection={self.collection},cursor={self.cursor},pass_started_at={self.pass_started_at},last_full_pass_at={self.last_full_pass_at},)"



    


class PeerLink(Base):
    """
    One row per (node, peer): the link state as that node last recorded it.
    """
    __tablename__ = 'PeerLink'

    id = Column(Text(), primary_key=True, nullable=False )
    node_id = Column(Text(), nullable=False )
    peer_id = Column(Text(), nullable=False )
    healthy = Column(Boolean(), nullable=False )
    changed_at = Column(DateTime(), nullable=False )
    digest = Column(Text(), nullable=False )
    

    def __repr__(self):
        return f"PeerLink(id={self.id},node_id={self.node_id},peer_id={self.peer_id},healthy={self.healthy},changed_at={self.changed_at},digest={self.digest},)"



    


