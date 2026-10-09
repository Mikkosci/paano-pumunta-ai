"""
Tests for router module
"""

import pytest
import json
import os
from router import Router, load_data, describe_itinerary


@pytest.fixture
def sample_routes():
    """Sample routes for testing"""
    return [
        {
            "name": "MRT-3",
            "type": "Train",
            "stops": ["North Ave", "Quezon Ave", "Cubao", "Shaw Blvd", "Ayala", "Taft Avenue"],
            "details": "Main rapid transit line along EDSA."
        },
        {
            "name": "Ayala-Washington Jeep",
            "type": "Jeepney",
            "stops": ["MRT Ayala", "Chino Roces", "Washington Street", "Gil Puyat Ave"],
            "details": "Board at the terminal near Telus/McKinley Exchange on Ayala Ave."
        },
        {
            "name": "Cubao-Divisoria Jeep",
            "type": "Jeepney",
            "stops": ["Gateway Cubao", "Aurora Blvd", "Stop & Shop", "Legarda", "Recto", "Divisoria"],
            "details": "Traverses Aurora Blvd all the way to Manila's shopping district."
        }
    ]


@pytest.fixture
def router(sample_routes):
    """Create router instance"""
    return Router(sample_routes)


class TestRouterInitialization:
    """Test router initialization"""
    
    def test_load_data(self, sample_routes):
        """Test loading data from JSON"""
        # Create temporary file
        with open("test_routes.json", "w") as f:
            json.dump(sample_routes, f)
        
        data = load_data("test_routes.json")
        assert len(data) == 3
        assert data[0]["name"] == "MRT-3"
        
        # Cleanup
        os.remove("test_routes.json")
    
    def test_load_data_file_not_found(self):
        """Test loading non-existent file"""
        data = load_data("nonexistent.json")
        assert data == []
    
    def test_build_graph(self, router):
        """Test graph building"""
        assert len(router.graph) > 0
        assert "North Ave" in router.graph
        assert "Cubao" in router.graph
    
    def test_extract_nodes(self, router):
        """Test node extraction"""
        assert len(router.nodes) > 0
        assert "North Ave" in router.nodes
        assert "Cubao" in router.nodes
        assert "Divisoria" in router.nodes
    
    def test_build_aliases(self, router):
        """Test alias building"""
        assert len(router.node_aliases) > 0
        assert "north ave" in router.node_aliases
        assert router.node_aliases["north ave"] == "North Ave"


class TestQueryParsing:
    """Test query parsing"""
    
    def test_parse_simple_query(self, router):
        """Test parsing simple query"""
        query = "Paano pumunta galing Cubao hanggang Divisoria?"
        result = router.parse_query(query)
        
        assert result["origin"] == "Cubao"
        assert result["dest"] == "Divisoria"
    
    def test_parse_with_to(self, router):
        """Test parsing with 'to'"""
        query = "How to get from Ayala to Shaw?"
        result = router.parse_query(query)
        
        assert result["origin"] == "Ayala"
        assert result["dest"] == "Shaw Blvd"
    
    def test_parse_incomplete_query(self, router):
        """Test parsing incomplete query"""
        query = "Paano pumunta?"
        result = router.parse_query(query)
        
        assert result["origin"] is None
        assert result["dest"] is None
    
    def test_parse_preference(self, router):
        """Test parsing preference"""
        query = "Paano pumunta galing Cubao hanggang Divisoria na direktso?"
        result = router.parse_query(query)
        
        assert result["preference"] == "direct"
    
    def test_parse_avoid(self, router):
        """Test parsing avoidance"""
        query = "Paano pumunta galing Cubao hanggang Divisoria iwas jeep?"
        result = router.parse_query(query)
        
        assert result["avoid"] == "jeep"


class TestRouting:
    """Test routing functionality"""
    
    def test_plan_basic_route(self, router):
        """Test basic route planning"""
        options = router.plan("Cubao", "Divisoria")
        
        assert len(options) > 0
        assert "legs" in options[0]
        assert len(options[0]["legs"]) > 0
    
    def test_plan_same_origin_dest(self, router):
        """Test planning same origin and destination"""
        options = router.plan("Cubao", "Cubao")
        
        assert options == []
    
    def test_plan_unknown_origin(self, router):
        """Test planning with unknown origin"""
        options = router.plan("Unknown Place", "Divisoria")
        
        assert options == []
    
    def test_plan_unknown_dest(self, router):
        """Test planning with unknown destination"""
        options = router.plan("Cubao", "Unknown Place")
        
        assert options == []
    
    def test_plan_multiple_options(self, router):
        """Test getting multiple route options"""
        options = router.plan("North Ave", "Divisoria")
        
        assert len(options) >= 1
    
    def test_preference_fewest_stops(self, router):
        """Test fewest stops preference"""
        options = router.plan("North Ave", "Divisoria", preference="fewest_stops")
        
        # Should return at least one option
        assert len(options) > 0
    
    def test_preference_direct(self, router):
        """Test direct preference"""
        options = router.plan("Cubao", "Divisoria", preference="direct")
        
        # Should prefer fewer transfers
        assert len(options) > 0


class TestLineInfo:
    """Test line information retrieval"""
    
    def test_get_mrt_info(self, router):
        """Test getting MRT information"""
        info = router.line_info("MRT-3")
        
        assert info is not None
        assert info["name"] == "MRT-3"
        assert len(info["stops"]) > 0
    
    def test_get_jeepp_info(self, router):
        """Test getting Jeepney information"""
        info = router.line_info("Ayala-Washington")
        
        assert info is not None
        assert info["type"] == "Jeepney"
    
    def test_get_nonexistent_line(self, router):
        """Test getting non-existent line"""
        info = router.line_info("NonExistent Line")
        
        assert info is None


class TestDescription:
    """Test itinerary description"""
    
    def test_describe_itinerary(self, router):
        """Test describing an itinerary"""
        options = router.plan("Cubao", "Divisoria")
        
        if options:
            description = describe_itinerary("Cubao", "Divisoria", options[0])
            
            assert isinstance(description, str)
            assert len(description) > 0
            assert "Cubao" in description
            assert "Divisoria" in description
    
    def test_describe_plan(self, router):
        """Test describing multiple plans"""
        options = router.plan("North Ave", "Divisoria")
        
        if options:
            description = describe_plan("North Ave", "Divisoria", options)
            
            assert isinstance(description, str)
            assert len(description) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
