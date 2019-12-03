/*
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This software may be used and distributed according to the terms of the
 * GNU General Public License found in the LICENSE file in the root
 * directory of this source tree.
 */

use bytes::Bytes;
use clap::Arg;
use cmdlib::{args, helpers::create_runtime};
use context::CoreContext;
use failure_ext::{Error, Result};
use fbinit::FacebookInit;
use futures::{stream, Future, IntoFuture, Stream};
use lfs_import_lib::lfs_upload;
use mercurial_types::blobs::File;

const NAME: &str = "lfs_import";

const ARG_LFS_HELPER: &str = "lfs-helper";
const ARG_CONCURRENCY: &str = "concurrency";
const ARG_POINTERS: &str = "pointers";

const DEFAULT_CONCURRENCY: usize = 16;

#[fbinit::main]
fn main(fb: FacebookInit) -> Result<()> {
    let app = args::MononokeApp::new(NAME)
        .with_advanced_args_hidden()
        .build()
        .version("0.0.0")
        .about("Import LFS blobs")
        .arg(
            Arg::with_name(ARG_CONCURRENCY)
                .long("concurrency")
                .takes_value(true)
                .help("The number of OIDs to process in parallel"),
        )
        .arg(
            Arg::with_name(ARG_LFS_HELPER)
                .required(true)
                .takes_value(true)
                .help("LFS Helper"),
        )
        .arg(
            Arg::with_name(ARG_POINTERS)
                .takes_value(true)
                .required(true)
                .min_values(1)
                .help("Raw LFS pointers to be imported"),
        );

    let matches = app.get_matches();
    args::init_cachelib(fb, &matches);

    let logger = args::init_logging(fb, &matches);
    let ctx = CoreContext::new_with_logger(fb, logger.clone());
    let blobrepo = args::open_repo(fb, &logger, &matches);
    let lfs_helper = matches.value_of(ARG_LFS_HELPER).unwrap().to_string();

    let concurrency: usize = matches
        .value_of(ARG_CONCURRENCY)
        .map_or(Ok(DEFAULT_CONCURRENCY), |j| j.parse())
        .map_err(Error::from)?;

    let entries: Result<Vec<_>> = matches
        .values_of(ARG_POINTERS)
        .unwrap()
        .into_iter()
        .map(|e| File::new(Bytes::from(e), None, None).get_lfs_content())
        .collect();

    let import = (blobrepo, entries)
        .into_future()
        .and_then(move |(blobrepo, entries)| {
            stream::iter_ok(entries)
                .map({
                    move |lfs| lfs_upload(ctx.clone(), blobrepo.clone(), lfs_helper.clone(), lfs)
                })
                .buffered(concurrency)
                .for_each(|_| Ok(()))
        });

    let mut runtime = create_runtime(None)?;
    let result = runtime.block_on(import);
    runtime.shutdown_on_idle();
    result
}
