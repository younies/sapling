/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This software may be used and distributed according to the terms of the
 * GNU General Public License version 2.
 */

//! Provides the c-bindings for `crate::backingstore`.

use std::collections::HashMap;
use std::ffi::CStr;
use std::os::raw::c_char;

use anyhow::Error;
use anyhow::Result;
use cxx::SharedPtr;
use libc::c_void;
use manifest::List;
use revisionstore::scmstore::FetchMode;
use revisionstore::scmstore::FileAuxData as ScmStoreFileAuxData;
use types::HgId;
use types::Key;

use crate::auxdata::FileAuxData;
use crate::backingstore::BackingStore;
use crate::cbytes::CBytes;
use crate::cfallible::CFallible;
use crate::cfallible::CFallibleBase;
use crate::request::Request;
use crate::slice::Slice;

#[cxx::bridge(namespace = sapling)]
pub(crate) mod ffi {
    pub struct BackingStoreOptions {
        allow_retries: bool,
    }

    #[repr(u8)]
    pub enum TreeEntryType {
        Tree,
        RegularFile,
        ExecutableFile,
        Symlink,
    }

    pub struct TreeEntry {
        hash: [u8; 20],
        name: Vec<u8>,
        ttype: TreeEntryType,
        has_size: bool,
        size: u64,
        has_sha1: bool,
        content_sha1: [u8; 20],
        has_blake3: bool,
        content_blake3: [u8; 32],
    }

    pub struct Tree {
        entries: Vec<TreeEntry>,
    }

    extern "Rust" {
        type BackingStore;

        pub unsafe fn sapling_backingstore_new(
            repository: &[c_char],
            options: &BackingStoreOptions,
        ) -> Result<Box<BackingStore>>;

        pub fn sapling_backingstore_get_manifest(
            store: &mut BackingStore,
            node: &[u8],
        ) -> Result<[u8; 20]>;

        pub fn sapling_backingstore_get_tree(
            store: &mut BackingStore,
            node: &[u8],
            local: bool,
        ) -> Result<SharedPtr<Tree>>;

        pub fn sapling_backingstore_flush(store: &mut BackingStore);
    }
}

fn fetch_mode_from_local(local: bool) -> FetchMode {
    if local {
        FetchMode::LocalOnly
    } else {
        FetchMode::AllowRemote
    }
}

pub unsafe fn sapling_backingstore_new(
    repository: &[c_char],
    options: &ffi::BackingStoreOptions,
) -> Result<Box<BackingStore>> {
    super::init::backingstore_global_init();

    let repo = CStr::from_ptr(repository.as_ptr()).to_str()?;
    let store = BackingStore::new(repo, options.allow_retries)?;
    Ok(Box::new(store))
}

pub fn sapling_backingstore_get_manifest(
    store: &mut BackingStore,
    node: &[u8],
) -> Result<[u8; 20]> {
    store.get_manifest(node)
}

pub fn sapling_backingstore_get_tree(
    store: &mut BackingStore,
    node: &[u8],
    local: bool,
) -> Result<SharedPtr<ffi::Tree>> {
    Ok(SharedPtr::new(
        store
            .get_tree(node, fetch_mode_from_local(local))
            .and_then(|opt| opt.ok_or_else(|| Error::msg("no tree found")))
            .and_then(|list| (list, HashMap::new()).try_into())?,
    ))
}

#[no_mangle]
pub extern "C" fn sapling_backingstore_get_tree_batch(
    store: &mut BackingStore,
    requests: Slice<Request>,
    local: bool,
    data: *mut c_void,
    resolve: unsafe extern "C" fn(*mut c_void, usize, CFallibleBase),
) {
    let keys: Vec<Key> = requests.slice().iter().map(|req| req.key()).collect();

    store.get_tree_batch(keys, fetch_mode_from_local(local), |idx, result| {
        let result: Result<(List, HashMap<HgId, ScmStoreFileAuxData>)> =
            result.and_then(|opt| opt.ok_or_else(|| Error::msg("no tree found")));
        let result: Result<ffi::Tree> = result.and_then(|list| list.try_into());
        let result: CFallible<ffi::Tree> = result.into();
        unsafe { resolve(data, idx, result.into()) };
    });
}

#[no_mangle]
pub extern "C" fn sapling_backingstore_get_blob(
    store: &mut BackingStore,
    node: Slice<u8>,
    local: bool,
) -> CFallibleBase {
    CFallible::make_with(|| {
        store
            .get_blob(node.slice(), fetch_mode_from_local(local))
            .and_then(|opt| opt.ok_or_else(|| Error::msg("no blob found")))
            .map(CBytes::from_vec)
    })
    .into()
}

#[no_mangle]
pub extern "C" fn sapling_backingstore_get_blob_batch(
    store: &mut BackingStore,
    requests: Slice<Request>,
    local: bool,
    data: *mut c_void,
    resolve: unsafe extern "C" fn(*mut c_void, usize, CFallibleBase),
) {
    let keys: Vec<Key> = requests.slice().iter().map(|req| req.key()).collect();
    store.get_blob_batch(keys, fetch_mode_from_local(local), |idx, result| {
        let result: CFallible<CBytes> = result
            .and_then(|opt| opt.ok_or_else(|| Error::msg("no blob found")))
            .map(CBytes::from_vec)
            .into();
        unsafe { resolve(data, idx, result.into()) };
    });
}

#[no_mangle]
pub extern "C" fn sapling_backingstore_get_file_aux(
    store: &mut BackingStore,
    node: Slice<u8>,
    local: bool,
) -> CFallibleBase {
    CFallible::<FileAuxData>::make_with(|| {
        store
            .get_file_aux(node.slice(), fetch_mode_from_local(local))
            .and_then(|opt| opt.ok_or_else(|| Error::msg("no file aux data found")))
            .map(|aux| aux.into())
    })
    .into()
}

#[no_mangle]
pub extern "C" fn sapling_backingstore_get_file_aux_batch(
    store: &mut BackingStore,
    requests: Slice<Request>,
    local: bool,
    data: *mut c_void,
    resolve: unsafe extern "C" fn(*mut c_void, usize, CFallibleBase),
) {
    let keys: Vec<Key> = requests.slice().iter().map(|req| req.key()).collect();

    store.get_file_aux_batch(keys, fetch_mode_from_local(local), |idx, result| {
        let result: Result<ScmStoreFileAuxData> =
            result.and_then(|opt| opt.ok_or_else(|| Error::msg("no file aux data found")));
        let result: CFallible<FileAuxData> = result.map(|aux| aux.into()).into();
        unsafe { resolve(data, idx, result.into()) };
    });
}

pub fn sapling_backingstore_flush(store: &mut BackingStore) {
    store.flush();
}
