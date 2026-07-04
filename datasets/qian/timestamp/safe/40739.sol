pragma solidity ^0.4.25;

contract DeflatingERC20 {
    address recoveredAddress;

    function permit(address owner, uint deadline) external {
        require(deadline >= block.timestamp, 'EXPIRED');
        require(recoveredAddress != address(0) && recoveredAddress == owner);
    }
}
