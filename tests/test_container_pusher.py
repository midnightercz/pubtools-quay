import logging
import mock
import pytest
import requests_mock
import requests

from pubtools._quay import exceptions
from pubtools._quay import quay_client
from pubtools._quay import container_image_pusher
from .utils.misc import sort_dictionary_sortable_values, compare_logs

# flake8: noqa: E501


@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_init(mock_quay_client, target_settings, container_multiarch_push_item):
    pusher = container_image_pusher.ContainerImagePusher(
        [container_multiarch_push_item], target_settings
    )

    assert pusher.push_items == [container_multiarch_push_item]
    assert pusher.target_settings == target_settings
    assert pusher.quay_host == "quay.io"
    mock_quay_client.assert_not_called()

    assert pusher.src_quay_client == mock_quay_client.return_value
    assert pusher.dest_quay_client == mock_quay_client.return_value
    assert mock_quay_client.call_args_list == [
        mock.call("src-quay-user", "src-quay-pass", "quay.io"),
        mock.call("dest-quay-user", "dest-quay-pass", "quay.io"),
    ]


@mock.patch("pubtools._quay.container_image_pusher.tag_images")
@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_tag_images(
    mock_quay_client,
    mock_tag_images,
    target_settings,
    container_multiarch_push_item,
):
    pusher = container_image_pusher.ContainerImagePusher(
        [container_multiarch_push_item], target_settings
    )

    pusher.run_tag_images(
        "source-ref:1", ["dest-ref:1", "dest-ref:2"], True, pusher.target_settings
    )
    mock_tag_images.assert_called_once_with(
        "source-ref:1",
        ["dest-ref:1", "dest-ref:2"],
        all_arch=True,
        quay_user="dest-quay-user",
        quay_password="dest-quay-pass",
        remote_exec=True,
        send_umb_msg=True,
        ssh_remote_host="127.0.0.1",
        ssh_username="ssh-user",
        ssh_password="ssh-password",
        umb_urls=["some-url1", "some-url2"],
        umb_cert="/etc/pub/umb-pub-cert-key.pem",
        umb_client_key="/etc/pub/umb-pub-cert-key.pem",
        umb_ca_cert="/etc/pki/tls/certs/ca-bundle.crt",
    )


@mock.patch("pubtools._quay.container_image_pusher.tag_images")
@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_copy_src_item(
    mock_quay_client,
    mock_tag_images,
    target_settings,
    container_source_push_item,
):
    pusher = container_image_pusher.ContainerImagePusher(
        [container_source_push_item], target_settings
    )
    pusher.copy_source_push_item(container_source_push_item)
    mock_tag_images.assert_called_once_with(
        "some-registry/src/repo:1",
        [
            "quay.io/some-namespace/target----repo:latest-test-tag",
            "quay.io/some-namespace/target----repo:1.0",
        ],
        all_arch=True,
        quay_user="dest-quay-user",
        quay_password="dest-quay-pass",
        remote_exec=True,
        send_umb_msg=True,
        ssh_remote_host="127.0.0.1",
        ssh_username="ssh-user",
        ssh_password="ssh-password",
        umb_urls=["some-url1", "some-url2"],
        umb_cert="/etc/pub/umb-pub-cert-key.pem",
        umb_client_key="/etc/pub/umb-pub-cert-key.pem",
        umb_ca_cert="/etc/pki/tls/certs/ca-bundle.crt",
    )


@mock.patch("pubtools._quay.container_image_pusher.ManifestListMerger")
@mock.patch("pubtools._quay.container_image_pusher.tag_images")
@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_merge_workflow(
    mock_quay_client,
    mock_tag_images,
    mock_ml_merger,
    target_settings,
    container_multiarch_push_item,
):
    mock_get_manifest = mock.MagicMock()
    mock_get_manifest.return_value = {"manifests": [{"digest": "digest1"}, {"digest": "digest2"}]}
    mock_quay_client.return_value.get_manifest = mock_get_manifest

    pusher = container_image_pusher.ContainerImagePusher(
        [container_multiarch_push_item], target_settings
    )
    pusher.run_merge_workflow(
        "registry/src/image:1", ["registry/dest1/image:1", "registry/dest2/image:2"]
    )
    mock_get_manifest.assert_called_once_with("registry/src/image:1", manifest_list=True)
    # test that src digests are copied to all dest repos
    assert mock_tag_images.call_args_list[0][0][1] == [
        "registry/dest1/image@digest1",
        "registry/dest2/image@digest1",
    ]
    assert mock_tag_images.call_args_list[1][0][1] == [
        "registry/dest1/image@digest2",
        "registry/dest2/image@digest2",
    ]

    assert mock_ml_merger.call_args_list == [
        mock.call("registry/src/image:1", "registry/dest1/image:1", host="quay.io"),
        mock.call("registry/src/image:1", "registry/dest2/image:2", host="quay.io"),
    ]

    assert len(mock_ml_merger.mock_calls) == 6


@mock.patch("pubtools._quay.container_image_pusher.ContainerImagePusher.run_merge_workflow")
@mock.patch("pubtools._quay.container_image_pusher.ManifestListMerger.get_missing_architectures")
@mock.patch("pubtools._quay.container_image_pusher.tag_images")
@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_copy_multiarch_item_no_extra_archs(
    mock_quay_client,
    mock_tag_images,
    mock_get_missing_archs,
    mock_merge_workflow,
    target_settings,
    container_multiarch_push_item,
):
    mock_get_manifest = mock.MagicMock()
    mock_get_manifest.return_value = {"manifest_list": "second_ml"}
    mock_quay_client.return_value.get_manifest = mock_get_manifest
    mock_get_missing_archs.return_value = []

    pusher = container_image_pusher.ContainerImagePusher(
        [container_multiarch_push_item], target_settings
    )
    pusher.copy_multiarch_push_item(container_multiarch_push_item, {"manifest_list": "first_ml"})

    mock_get_manifest.assert_called_once_with(
        "quay.io/some-namespace/target----repo:latest-test-tag", manifest_list=True
    )
    assert mock_tag_images.call_count == 1
    assert mock_tag_images.call_args_list[0][0] == (
        "some-registry/src/repo:1",
        ["quay.io/some-namespace/target----repo:latest-test-tag"],
    )


@mock.patch("pubtools._quay.container_image_pusher.ContainerImagePusher.run_merge_workflow")
@mock.patch("pubtools._quay.container_image_pusher.ManifestListMerger.get_missing_architectures")
@mock.patch("pubtools._quay.container_image_pusher.tag_images")
@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_copy_multiarch_item_no_dest_ml(
    mock_quay_client,
    mock_tag_images,
    mock_get_missing_archs,
    mock_merge_workflow,
    target_settings,
    container_multiarch_push_item,
):
    mock_get_manifest = mock.MagicMock()

    response = mock.MagicMock()
    response.status_code = 404
    mock_get_manifest.side_effect = requests.exceptions.HTTPError("some error", response=response)
    mock_quay_client.return_value.get_manifest = mock_get_manifest
    mock_get_missing_archs.return_value = []

    pusher = container_image_pusher.ContainerImagePusher(
        [container_multiarch_push_item], target_settings
    )
    pusher.copy_multiarch_push_item(
        container_multiarch_push_item,
        {"manifest_list": "first_ml"},
    )

    mock_get_manifest.assert_called_once_with(
        "quay.io/some-namespace/target----repo:latest-test-tag", manifest_list=True
    )

    assert mock_tag_images.call_count == 1
    assert mock_tag_images.call_args_list[0][0] == (
        "some-registry/src/repo:1",
        ["quay.io/some-namespace/target----repo:latest-test-tag"],
    )

    mock_merge_workflow.assert_not_called()


@mock.patch("pubtools._quay.container_image_pusher.ContainerImagePusher.run_merge_workflow")
@mock.patch("pubtools._quay.container_image_pusher.ManifestListMerger.get_missing_architectures")
@mock.patch("pubtools._quay.container_image_pusher.tag_images")
@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_copy_multiarch_item_network_error(
    mock_quay_client,
    mock_tag_images,
    mock_get_missing_archs,
    mock_merge_workflow,
    target_settings,
    container_multiarch_push_item,
):
    mock_get_manifest = mock.MagicMock()

    response = mock.MagicMock()
    response.status_code = 500
    mock_get_manifest.side_effect = requests.exceptions.HTTPError("bad error", response=response)

    mock_quay_client.return_value.get_manifest = mock_get_manifest
    mock_get_missing_archs.return_value = []

    pusher = container_image_pusher.ContainerImagePusher(
        [container_multiarch_push_item], target_settings
    )
    with pytest.raises(requests.exceptions.HTTPError, match="bad error"):
        pusher.copy_multiarch_push_item(
            container_multiarch_push_item, {"manifest_list": "first_ml"}
        )


@mock.patch("pubtools._quay.container_image_pusher.ContainerImagePusher.run_merge_workflow")
@mock.patch("pubtools._quay.container_image_pusher.ManifestListMerger.get_missing_architectures")
@mock.patch("pubtools._quay.container_image_pusher.tag_images")
@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_copy_multiarch_item_missing_archs(
    mock_quay_client,
    mock_tag_images,
    mock_get_missing_archs,
    mock_merge_workflow,
    target_settings,
    container_multiarch_push_item,
):
    mock_get_manifest = mock.MagicMock()

    mock_get_manifest.side_effect = {"manifest_list": "second_ml"}
    mock_quay_client.return_value.get_manifest = mock_get_manifest
    mock_get_missing_archs.return_value = [{"arch": "x86_64"}, {"arch": "amd64"}]

    pusher = container_image_pusher.ContainerImagePusher(
        [container_multiarch_push_item], target_settings
    )
    pusher.copy_multiarch_push_item(container_multiarch_push_item, {"manifest_list": "first_ml"})

    mock_get_manifest.assert_called_once_with(
        "quay.io/some-namespace/target----repo:latest-test-tag", manifest_list=True
    )

    assert mock_merge_workflow.call_count == 1
    assert mock_merge_workflow.call_args_list[0][0] == (
        "some-registry/src/repo:1",
        ["quay.io/some-namespace/target----repo:latest-test-tag"],
    )

    mock_tag_images.assert_not_called()


@mock.patch("pubtools._quay.container_image_pusher.ContainerImagePusher.copy_source_push_item")
@mock.patch("pubtools._quay.container_image_pusher.ContainerImagePusher.copy_multiarch_push_item")
@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_push_container_items_src_item(
    mock_quay_client,
    mock_copy_multiarch,
    mock_copy_src,
    target_settings,
    container_source_push_item,
):
    mock_get_manifest = mock.MagicMock()

    mock_get_manifest.side_effect = exceptions.ManifestTypeError("no manifest list")
    mock_quay_client.return_value.get_manifest = mock_get_manifest

    pusher = container_image_pusher.ContainerImagePusher(
        [container_source_push_item], target_settings
    )
    pusher.push_container_images()

    mock_copy_multiarch.assert_not_called()
    mock_copy_src.assert_called_once()


@mock.patch("pubtools._quay.container_image_pusher.ContainerImagePusher.copy_source_push_item")
@mock.patch("pubtools._quay.container_image_pusher.ContainerImagePusher.copy_multiarch_push_item")
@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_push_container_items_arch_item_error(
    mock_quay_client,
    mock_copy_multiarch,
    mock_copy_src,
    target_settings,
    container_multiarch_push_item,
):
    mock_get_manifest = mock.MagicMock()

    mock_get_manifest.side_effect = exceptions.ManifestTypeError("no manifest list")
    mock_quay_client.return_value.get_manifest = mock_get_manifest

    pusher = container_image_pusher.ContainerImagePusher(
        [container_multiarch_push_item], target_settings
    )
    with pytest.raises(exceptions.BadPushItem, match=".*contains a single-arch.*"):
        pusher.push_container_images()


@mock.patch("pubtools._quay.container_image_pusher.ContainerImagePusher.copy_source_push_item")
@mock.patch("pubtools._quay.container_image_pusher.ContainerImagePusher.copy_multiarch_push_item")
@mock.patch("pubtools._quay.container_image_pusher.QuayClient")
def test_push_container_items_multiarch_item(
    mock_quay_client,
    mock_copy_multiarch,
    mock_copy_src,
    target_settings,
    container_multiarch_push_item,
):
    mock_get_manifest = mock.MagicMock()

    mock_get_manifest.return_value = {"some-manifest": "manifest-list"}
    mock_quay_client.return_value.get_manifest = mock_get_manifest

    pusher = container_image_pusher.ContainerImagePusher(
        [container_multiarch_push_item], target_settings
    )
    pusher.push_container_images()

    mock_copy_src.assert_not_called()
    mock_copy_multiarch.assert_called_once()
