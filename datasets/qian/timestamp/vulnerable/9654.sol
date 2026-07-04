pragma solidity ^0.4.25;

contract SimpleBet {
	function random() view returns (uint8) {
        return uint8(uint256(keccak256(block.timestamp, block.difficulty)) % 256);
    }
}