/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import {DropdownFields} from './DropdownFields';
import {OperationDisabledButton} from './OperationDisabledButton';
import {Tooltip} from './Tooltip';
import {T} from './i18n';
import {VSCodeButton} from '@vscode/webview-ui-toolkit/react';
import {Icon} from 'shared/Icon';

export function BulkActionsMenu() {
  return (
    <Tooltip
      component={dismiss => <BulkActions dismiss={dismiss} />}
      trigger="click"
      placement="bottom"
      title={<T>Bulk Actions</T>}>
      <VSCodeButton appearance="icon" data-testid="bulk-actions-button">
        <Icon icon="run-all" />
      </VSCodeButton>
    </Tooltip>
  );
}

function BulkActions({dismiss}: {dismiss: () => void}) {
  return (
    <DropdownFields
      title={<T>Bulk Actions</T>}
      icon="run-all"
      className="bulk-actions-dropdown"
      data-testid="bulk-actions-dropdown">
      <OperationDisabledButton
        appearance="secondary"
        contextKey={`rebase-all`}
        runOperation={() => {
          dismiss();
          return undefined;
        }}>
        <T>Rebase All Draft Commits</T>
      </OperationDisabledButton>
    </DropdownFields>
  );
}