/*
 *  Copyright (c) 2016-present, Facebook, Inc.
 *  All rights reserved.
 *
 *  This source code is licensed under the BSD-style license found in the
 *  LICENSE file in the root directory of this source tree. An additional grant
 *  of patent rights can be found in the PATENTS file in the same directory.
 *
 */
#include "eden/fs/store/test/LocalStoreTest.h"
#include "eden/fs/store/MemoryLocalStore.h"
#include "eden/fs/store/SqliteLocalStore.h"

namespace {

using namespace facebook::eden;

LocalStoreImplResult makeMemoryLocalStore(FaultInjector*) {
  return {std::nullopt, std::make_unique<MemoryLocalStore>()};
}

LocalStoreImplResult makeSqliteLocalStore(FaultInjector*) {
  auto tempDir = makeTempDir();
  auto store = std::make_unique<SqliteLocalStore>(
      AbsolutePathPiece{tempDir.path().string()} + "sqlite"_pc);
  return {std::move(tempDir), std::move(store)};
}

INSTANTIATE_TEST_CASE_P(
    Memory,
    LocalStoreTest,
    ::testing::Values(makeMemoryLocalStore));

INSTANTIATE_TEST_CASE_P(
    Sqlite,
    LocalStoreTest,
    ::testing::Values(makeSqliteLocalStore));

} // namespace
