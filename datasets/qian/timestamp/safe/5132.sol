pragma solidity ^0.4.25;

contract COD {

    mapping(address => uint) balances;

    function burn (uint256 _burntAmount) public returns (bool success) {
    	require(balances[msg.sender] >= _burntAmount && block.timestamp > 10);
    	return true;
	}
}